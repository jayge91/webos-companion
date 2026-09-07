from __future__ import annotations

import asyncio

import pytest

from webos_companion import __main__ as cli
from webos_companion.config import Config, load_client_key
from tests.fake_tv import FakeTV


@pytest.fixture
def cfg(xdg, tmp_path):
    def _make(tv: FakeTV, **kw) -> Config:
        c = Config(ip="127.0.0.1", ssl=False, port=tv.port, **kw)
        c.save()
        return c

    return _make


async def test_cli_off_and_on(cfg):
    async with FakeTV(known_key="k") as tv:
        from webos_companion import config as cfgmod

        cfgmod.save_client_key("k")
        conf = cfg(tv)
        assert await cli._cmd_simple(conf, "off") == 0
        assert await cli._cmd_simple(conf, "on") == 0
    assert tv.uris == [
        "ssap://com.webos.service.tvpower/power/turnOffScreen",
        "ssap://com.webos.service.tvpower/power/turnOnScreen",
    ]


async def test_cli_pair_saves_key(cfg, monkeypatch):
    monkeypatch.setattr(cli.net, "neigh_mac", lambda ip: "aa:bb:cc:dd:ee:ff")
    async with FakeTV(new_key="paired-key") as tv:
        conf = cfg(tv)
        rc = await cli._cmd_pair(conf)
    assert rc == 0
    assert load_client_key() == "paired-key"
    assert Config.load().mac == "aa:bb:cc:dd:ee:ff"


async def test_cli_status_runs_without_drm(cfg, capsys):
    async with FakeTV(known_key="k") as tv:
        from webos_companion import config as cfgmod

        cfgmod.save_client_key("k")
        conf = cfg(tv)
        rc = await cli._cmd_status(conf)
    assert rc == 0
    out = capsys.readouterr().out
    assert "tv power:" in out
    assert "paired:     yes" in out


async def test_cli_simple_reports_unreachable(cfg):
    conf = Config(ip="127.0.0.1", ssl=False, port=1)
    conf.save()
    assert await cli._cmd_simple(conf, "off") == 1


async def test_cli_run_dry_run_never_touches_tv(cfg, drm_tree, monkeypatch):
    import functools

    root, mk = drm_tree
    conn = mk("HDMI-A-1", vendor="GSM", dpms="On")
    from webos_companion.triggers.drm import DrmWatcher

    monkeypatch.setattr(
        cli, "DrmWatcher", functools.partial(DrmWatcher, sysfs_root=root)
    )

    async with FakeTV(known_key="k") as tv:
        from webos_companion import config as cfgmod

        cfgmod.save_client_key("k")
        conf = cfg(tv, poll_interval=0.05)

        async def drive():
            await asyncio.sleep(0.15)
            (conn / "dpms").write_text("Off\n")  # simulate the desktop blanking
            await asyncio.sleep(0.15)

        task = asyncio.create_task(drive())
        rc = await cli._cmd_run(conf, dry_run=True, seconds=0.6)
        await task
    assert rc == 0
    # handshake + a power-state read are fine; screen commands must NOT appear.
    assert all("turnOffScreen" not in u and "turnOnScreen" not in u for u in tv.uris)

