from __future__ import annotations

import pytest

from webos_companion import discover
from webos_companion.discover import TvCandidate, _clean_name, _looks_webos


@pytest.fixture(autouse=True)
def _no_real_network(monkeypatch):
    """Never touch the real network from a discover() test unless it opts back in."""
    monkeypatch.setattr(discover, "_ssdp_search", lambda t: {})
    monkeypatch.setattr(discover, "_airplay_info", lambda ip, *a, **k: {})
    monkeypatch.setattr(discover, "_has_lg_cert", lambda ip, *a, **k: False)
    monkeypatch.setattr(
        discover.socket, "gethostbyaddr", lambda ip: (_ for _ in ()).throw(OSError())
    )
    monkeypatch.setattr(discover.net, "ping", lambda ip, t=1.0: True)
    monkeypatch.setattr(discover.net, "neigh_mac", lambda ip: None)
    monkeypatch.setattr(discover.net, "arp_neighbours", lambda: [])
    monkeypatch.setattr(discover.net, "tcp_open", lambda *a, **k: False)


def test_looks_webos():
    assert _looks_webos({"server": "WebOS/1.4 UPnP/1.0"}) is True
    assert _looks_webos({"x": "LG Electronics"}) is True
    assert _looks_webos({"server": "Roku/9.0"}) is False


def test_clean_name():
    assert _clean_name("[LG] Living Room OLED") == "Living Room OLED"
    assert _clean_name("  Living Room  ") == "Living Room"


def test_candidate_describe():
    c = TvCandidate(
        "192.168.1.42",
        mac="80:5b:65:a1:b2:c3",
        name="Living Room OLED",
        model="OLED42C2PUA",
        webos=True,
    )
    d = c.describe()
    assert "192.168.1.42" in d and "Living Room OLED" in d
    assert "[OLED42C2PUA]" in d and "(LG webOS TV)" in d

    bare = TvCandidate("192.168.1.43", ssap_port=3001)
    assert bare.describe().endswith("answers on port 3001")


def test_reverse_dns_trims_suffix(monkeypatch):
    monkeypatch.setattr(discover.socket, "gethostbyaddr", lambda ip: ("LGwebOSTV.local", [], [ip]))
    assert discover._reverse_dns("1.2.3.4") == "LGwebOSTV"
    monkeypatch.setattr(discover.socket, "gethostbyaddr", lambda ip: ("box.corp.example.com", [], [ip]))
    assert discover._reverse_dns("1.2.3.4") == "box"
    monkeypatch.setattr(
        discover.socket, "gethostbyaddr", lambda ip: (_ for _ in ()).throw(OSError())
    )
    assert discover._reverse_dns("1.2.3.4") == ""


def test_discover_uses_airplay_model_and_name(monkeypatch):
    monkeypatch.setattr(discover.net, "arp_neighbours", lambda: ["192.168.1.42"])
    monkeypatch.setattr(discover.net, "tcp_open", lambda ip, port, timeout=0.4: port == 3001)
    monkeypatch.setattr(
        discover,
        "_airplay_info",
        lambda ip, *a, **k: {
            "name": "[LG] Living Room OLED",
            "model": "OLED42C2PUA",
            "manufacturer": "LG",
        },
    )
    [tv] = discover.discover(timeout=0.1)
    assert tv.webos is True
    assert tv.name == "Living Room OLED"
    assert tv.model == "OLED42C2PUA"


def test_discover_confirms_webos_by_tls_cert_when_no_airplay(monkeypatch):
    monkeypatch.setattr(discover.net, "arp_neighbours", lambda: ["192.168.1.43"])
    monkeypatch.setattr(discover.net, "tcp_open", lambda ip, port, timeout=0.4: port == 3001)
    monkeypatch.setattr(discover, "_has_lg_cert", lambda ip, *a, **k: True)
    monkeypatch.setattr(discover, "_reverse_dns", lambda ip, *a, **k: "LGwebOSTV")
    [tv] = discover.discover(timeout=0.1)
    assert tv.webos is True
    assert tv.name == "LGwebOSTV"
    assert tv.model == ""


def test_discover_excludes_non_tv(monkeypatch):
    monkeypatch.setattr(
        discover, "_ssdp_search", lambda t: {"10.0.0.9": {"server": "Sonos"}}
    )
    monkeypatch.setattr(discover.net, "arp_neighbours", lambda: ["10.0.0.9"])
    assert discover.discover(timeout=0.1) == []
