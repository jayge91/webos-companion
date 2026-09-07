"""Small network helpers shared by the CLI and discovery."""

from __future__ import annotations

import re
import socket
import subprocess

_MAC_RE = re.compile(r"lladdr\s+([0-9a-fA-F:]{17})")


def ping(ip: str, timeout: float = 1.0) -> bool:
    try:
        return (
            subprocess.run(
                ["ping", "-c1", f"-W{max(1, int(timeout))}", ip],
                capture_output=True,
                timeout=timeout + 2,
            ).returncode
            == 0
        )
    except (OSError, subprocess.SubprocessError):
        return False


def tcp_open(ip: str, port: int, timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except OSError:
        return False


def arp_neighbours() -> list[str]:
    """IPv4 addresses currently in the kernel neighbour table (reachable-ish)."""
    try:
        out = subprocess.run(
            ["ip", "-4", "neigh", "show"], capture_output=True, text=True, timeout=5
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    ips: list[str] = []
    for line in out.splitlines():
        parts = line.split()
        if not parts or not parts[0][:1].isdigit():
            continue
        if "FAILED" in line or "INCOMPLETE" in line:
            continue
        ips.append(parts[0])
    return ips


def neigh_mac(ip: str) -> str | None:
    try:
        out = subprocess.run(
            ["ip", "neigh", "show", ip], capture_output=True, text=True, timeout=5
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    m = _MAC_RE.search(out)
    return m.group(1).lower() if m else None


def looks_like_ipv4(text: str) -> bool:
    parts = text.split(".")
    return len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts)
