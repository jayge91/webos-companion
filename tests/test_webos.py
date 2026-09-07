from __future__ import annotations

import asyncio

import pytest

from webos_companion.webos import (
    WebOsClient,
    WebOsError,
    build_magic_packet,
    route_exists,
)
from tests.fake_tv import FakeTV


def _client(tv: FakeTV, **kw) -> WebOsClient:
    return WebOsClient("127.0.0.1", use_ssl=False, port=tv.port, **kw)


async def test_pairing_captures_new_key():
    captured: list[str] = []
    async with FakeTV(new_key="fresh-key") as tv:
        c = _client(tv, on_client_key=captured.append)
        await c.connect(pair_timeout=5)
        assert c.client_key == "fresh-key"
        assert captured == ["fresh-key"]
        await c.close()


async def test_pairing_reuses_existing_key():
    async with FakeTV(known_key="good") as tv:
        c = _client(tv, client_key="good")
        await c.connect(pair_timeout=5)
        assert c.connected
        await c.close()


async def test_pairing_rejected_key_raises():
    async with FakeTV(known_key="good") as tv:
        c = _client(tv, client_key="wrong")
        with pytest.raises(WebOsError):
            await c.connect(pair_timeout=5)
        assert not c.connected


async def test_pairing_waits_for_prompt_then_registers():
    async with FakeTV(pair_delay=0.3, new_key="k2") as tv:
        c = _client(tv)
        await c.connect(pair_timeout=5)
        assert c.client_key == "k2"
        await c.close()


async def test_command_roundtrip():
    async with FakeTV(known_key="k") as tv:
        c = _client(tv, client_key="k")
        await c.connect(pair_timeout=5)
        await c.turn_off_screen()
        await c.turn_on_screen()
        await c.system_off()
        state = await c.get_power_state()
        await c.close()
    assert tv.uris == [
        "ssap://com.webos.service.tvpower/power/turnOffScreen",
        "ssap://com.webos.service.tvpower/power/turnOnScreen",
        "ssap://system/turnOff",
        "ssap://com.webos.service.tvpower/power/getPowerState",
    ]
    assert state["state"] == "Active"


async def test_reconnects_after_drop():
    async with FakeTV(known_key="k", drop_after=1) as tv:
        c = _client(tv, client_key="k")
        await c.connect(pair_timeout=5)
        await c.turn_off_screen()          # server drops the socket right after
        await asyncio.sleep(0.05)
        assert not c.connected
        await c.turn_on_screen()           # transparently reconnects
        await c.close()
    assert tv.connections == 2


async def test_request_timeout(monkeypatch):
    async with FakeTV(known_key="k") as tv:
        c = _client(tv, client_key="k")
        await c.connect(pair_timeout=5)

        async def _swallow(ws, msg):  # server accepts but never answers
            return

        monkeypatch.setattr(tv, "_respond", _swallow)
        with pytest.raises(asyncio.TimeoutError):
            await c.request("ssap://x", timeout=0.2)
        await c.close()


def test_build_magic_packet():
    pkt = build_magic_packet("AB:CD:EF:12:34:56")
    assert len(pkt) == 102
    assert pkt[:6] == b"\xff" * 6
    assert pkt[6:12] == bytes.fromhex("abcdef123456")
    assert pkt[12:18] == bytes.fromhex("abcdef123456")


@pytest.mark.parametrize("bad", ["", "AB:CD:EF:12:34", "zz:zz:zz:zz:zz:zz"])
def test_build_magic_packet_rejects_bad(bad):
    with pytest.raises(ValueError):
        build_magic_packet(bad)


def test_send_wol_targets_broadcast_and_ip():
    sent: list[tuple[bytes, list]] = []
    c = WebOsClient(
        "192.168.1.42",
        mac="ab:cd:ef:12:34:56",
        wol_broadcast="255.255.255.255",
        udp_sender=lambda pkt, targets: sent.append((pkt, list(targets))),
    )
    c.send_wol()
    pkt, targets = sent[0]
    assert len(pkt) == 102
    assert ("255.255.255.255", 9) in targets
    assert ("192.168.1.42", 9) in targets
    assert ("255.255.255.255", 7) in targets  # also the legacy WOL port


async def test_send_wol_burst_sends_several():
    sent: list = []
    c = WebOsClient(
        "192.168.1.42",
        mac="ab:cd:ef:12:34:56",
        udp_sender=lambda pkt, targets: sent.append(pkt),
    )
    await c.send_wol_burst(count=4, spacing=0)
    assert len(sent) == 4


async def test_ensure_on_force_unblank_unblanks_even_when_active():
    async with FakeTV(known_key="k", power_state="Active") as tv:
        c = _client(tv, client_key="k")
        await c.connect(pair_timeout=5)
        await c.ensure_on(allow_wol=False, force_unblank=True)
        await c.close()
    assert tv.uris[-1].endswith("turnOnScreen")


async def test_ensure_on_unblanks_when_screen_is_off():
    async with FakeTV(known_key="k", power_state="Screen Off") as tv:
        c = _client(tv, client_key="k")
        await c.connect(pair_timeout=5)
        await c.ensure_on(allow_wol=False)
        await c.close()
    assert tv.uris[-1].endswith("turnOnScreen")


async def test_ensure_on_is_noop_when_already_active():
    async with FakeTV(known_key="k", power_state="Active") as tv:
        c = _client(tv, client_key="k")
        await c.connect(pair_timeout=5)
        await c.ensure_on(allow_wol=False)
        await c.close()
    assert not any(u.endswith("turnOnScreen") for u in tv.uris)


async def test_ensure_on_survives_turn_on_screen_error():
    # TV reachable but returns "500 Application error" for turnOnScreen
    # (real behaviour when the panel is already lit after a WOL wake).
    async with FakeTV(
        known_key="k", power_state="Screen Off", error_uris={"turnOnScreen"}
    ) as tv:
        c = _client(tv, client_key="k")
        await c.connect(pair_timeout=5)
        await c.ensure_on(allow_wol=False)  # reachable => success, must not raise
        await c.close()


async def test_ensure_on_unreachable_raises_quickly():
    c = WebOsClient("127.0.0.1", use_ssl=False, port=1, mac=None, pair_timeout=1)
    with pytest.raises(ConnectionError):
        await c.ensure_on(allow_wol=False)


def test_route_exists():
    assert route_exists("127.0.0.1") is True
    assert route_exists("") is False


async def test_wait_for_network_returns_when_route_appears():
    calls = {"n": 0}

    def check(_host):
        calls["n"] += 1
        return calls["n"] >= 3

    c = WebOsClient("10.0.0.9", route_check=check)
    assert await c.wait_for_network(timeout=5, interval=0.01) is True
    assert calls["n"] == 3


async def test_wait_for_network_times_out():
    c = WebOsClient("10.0.0.9", route_check=lambda _h: False)
    assert await c.wait_for_network(timeout=0.2, interval=0.05) is False


async def test_ensure_on_gate_blocks_before_any_socket_or_wol():
    sent: list = []
    async with FakeTV(known_key="k") as tv:
        c = _client(
            tv,
            client_key="k",
            mac="ab:cd:ef:12:34:56",
            route_check=lambda _h: False,
            udp_sender=lambda p, t: sent.append(1),
        )
        with pytest.raises(ConnectionError):
            await c.ensure_on(network_wait=0.2)
    assert tv.connections == 0  # never tried to open the socket
    assert sent == []           # never sent WOL
