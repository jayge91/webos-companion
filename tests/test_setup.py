from __future__ import annotations

from webos_companion import __main__ as cli
from webos_companion.config import Config
from webos_companion.discover import TvCandidate


def _answers(monkeypatch, seq):
    it = iter(seq)
    monkeypatch.setattr("builtins.input", lambda *a: next(it, ""))


def test_choose_tv_by_number_returns_ip_and_mac(monkeypatch, capsys):
    cands = [
        TvCandidate("192.168.1.42", mac="80:5b:65:a1:b2:c3", webos=True),
        TvCandidate("192.168.1.44", mac="aa:bb:cc:dd:ee:ff", ssap_port=3001),
    ]
    _answers(monkeypatch, ["2"])
    ip, mac = cli._choose_tv(cands, "")
    assert (ip, mac) == ("192.168.1.44", "aa:bb:cc:dd:ee:ff")
    out = capsys.readouterr().out
    assert "1) 192.168.1.42" in out and "LG webOS TV" in out


def test_choose_tv_accepts_typed_ip(monkeypatch):
    cands = [TvCandidate("192.168.1.42", webos=True)]
    monkeypatch.setattr(cli.net, "neigh_mac", lambda ip: "11:22:33:44:55:66")
    _answers(monkeypatch, ["10.0.0.5"])
    assert cli._choose_tv(cands, "") == ("10.0.0.5", "11:22:33:44:55:66")


def test_choose_tv_no_candidates_prompts_for_ip(monkeypatch):
    monkeypatch.setattr(cli.net, "neigh_mac", lambda ip: None)
    _answers(monkeypatch, ["192.168.1.9"])
    assert cli._choose_tv([], "") == ("192.168.1.9", None)


def test_choose_tv_rejects_garbage_then_accepts(monkeypatch, capsys):
    cands = [TvCandidate("192.168.1.42", mac="80:5b:65:a1:b2:c3", webos=True)]
    _answers(monkeypatch, ["nonsense", "9", "1"])
    ip, _ = cli._choose_tv(cands, "")
    assert ip == "192.168.1.42"
    assert "list numbers" in capsys.readouterr().out


async def test_setup_requires_a_tty(monkeypatch, capsys):
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False)
    rc = await cli._cmd_setup(Config())
    assert rc == 2
    assert "interactive" in capsys.readouterr().err


async def test_setup_full_flow(xdg, monkeypatch):
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(
        cli.discover,
        "discover",
        lambda: [TvCandidate("192.168.1.42", mac="80:5B:65:A1:B2:C3", webos=True)],
    )
    monkeypatch.setattr(cli.net, "ping", lambda ip: True)
    monkeypatch.setattr(cli, "_detect_connector", lambda: "HDMI-A-1")
    # choose #1, accept MAC, blank connector, then install service
    _answers(monkeypatch, ["1", "", "", "y"])

    paired: list[str] = []
    installed: list[bool] = []

    async def fake_pair(cfg):
        paired.append(cfg.ip)
        return 0

    monkeypatch.setattr(cli, "_cmd_pair", fake_pair)
    monkeypatch.setattr(cli.service, "install", lambda **kw: installed.append(True))
    monkeypatch.setattr(cli.service, "status_text", lambda: "active (enabled)")

    rc = await cli._cmd_setup(Config())
    assert rc == 0

    saved = Config.load()
    assert saved.ip == "192.168.1.42"
    assert saved.mac == "80:5b:65:a1:b2:c3"  # lower-cased
    assert saved.connector == ""
    assert paired == ["192.168.1.42"]
    assert installed == [True]


async def test_setup_aborts_without_ip(xdg, monkeypatch, capsys):
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(cli.discover, "discover", lambda: [])
    _answers(monkeypatch, [""])  # no candidates, empty IP
    rc = await cli._cmd_setup(Config())
    assert rc == 2
    assert "IP address is required" in capsys.readouterr().err
