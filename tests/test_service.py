from __future__ import annotations

import subprocess

import webos_companion.service as svc


def _fake_run(record):
    def run(cmd, **kw):
        record.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    return run


def test_status_not_installed(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert "not installed" in svc.status_text()


def test_install_writes_unit_and_enables(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(svc.shutil, "which", lambda _n: "/opt/pipx/bin/webos-companion")
    calls: list[list[str]] = []
    monkeypatch.setattr(svc.subprocess, "run", _fake_run(calls))

    svc.install()

    unit = tmp_path / ".config/systemd/user/webos-companion.service"
    assert unit.exists()
    text = unit.read_text()
    assert "ExecStart=/opt/pipx/bin/webos-companion run" in text
    assert ["systemctl", "--user", "daemon-reload"] in calls
    assert ["systemctl", "--user", "enable", "--now", "webos-companion.service"] in calls


def test_install_falls_back_to_local_bin(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(svc.shutil, "which", lambda _n: None)
    monkeypatch.setattr(svc.subprocess, "run", _fake_run([]))
    svc.install()
    text = (tmp_path / ".config/systemd/user/webos-companion.service").read_text()
    assert f"ExecStart={tmp_path}/.local/bin/webos-companion run" in text


def test_install_raises_on_systemctl_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(svc.shutil, "which", lambda _n: "/x/webos-companion")

    def run(cmd, **kw):
        rc = 0 if "daemon-reload" in cmd else 1
        return subprocess.CompletedProcess(cmd, rc, stdout="", stderr="boom")

    monkeypatch.setattr(svc.subprocess, "run", run)
    import pytest

    with pytest.raises(RuntimeError, match="boom"):
        svc.install()


def test_remove_deletes_unit(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    unit = tmp_path / ".config/systemd/user/webos-companion.service"
    unit.parent.mkdir(parents=True)
    unit.write_text("x")
    monkeypatch.setattr(svc.subprocess, "run", _fake_run([]))
    svc.remove()
    assert not unit.exists()
