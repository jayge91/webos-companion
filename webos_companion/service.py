"""Install / remove the systemd --user service that runs the daemon."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

UNIT_NAME = "webos-companion.service"

_UNIT_TEMPLATE = """\
# Installed by `webos-companion service install`.
[Unit]
Description=webOS Companion — follow the display power state on an LG webOS TV
After=graphical-session.target
PartOf=graphical-session.target

[Service]
Type=simple
ExecStart={exec_start} run
Restart=on-failure
RestartSec=5
TimeoutStopSec=10

[Install]
WantedBy=graphical-session.target
"""


def unit_path() -> Path:
    return Path.home() / ".config" / "systemd" / "user" / UNIT_NAME


def _exe() -> str:
    return shutil.which("webos-companion") or str(
        Path.home() / ".local" / "bin" / "webos-companion"
    )


def _systemctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["systemctl", "--user", *args], text=True, capture_output=True
    )


def install(*, enable: bool = True, start: bool = True) -> None:
    dest = unit_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(_UNIT_TEMPLATE.format(exec_start=_exe()))
    _systemctl("daemon-reload")
    if enable and start:
        _run_checked("enable", "--now", UNIT_NAME)
    elif enable:
        _run_checked("enable", UNIT_NAME)
    elif start:
        _run_checked("start", UNIT_NAME)


def remove() -> None:
    _systemctl("disable", "--now", UNIT_NAME)
    unit_path().unlink(missing_ok=True)
    _systemctl("daemon-reload")


def status_text() -> str:
    """Short service state, no label prefix (callers add their own)."""
    if not unit_path().exists():
        return "not installed"
    active = _systemctl("is-active", UNIT_NAME).stdout.strip() or "unknown"
    enabled = _systemctl("is-enabled", UNIT_NAME).stdout.strip() or "unknown"
    return f"{active} ({enabled}) — {unit_path()}"


def _run_checked(*args: str) -> None:
    result = _systemctl(*args)
    if result.returncode != 0:
        raise RuntimeError(
            f"systemctl --user {' '.join(args)} failed: "
            f"{(result.stderr or result.stdout).strip()}"
        )
