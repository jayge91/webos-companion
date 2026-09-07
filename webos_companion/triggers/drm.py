"""Watch a DRM connector's power state via ``/sys/class/drm/<card>-<conn>/dpms``."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from . import Dispatch, Event

log = logging.getLogger(__name__)

_EDID_HEADER = bytes.fromhex("00ffffffffffff00")
_LG_PNP_IDS = {"GSM", "LGD"}  # LG Electronics, LG Display


def _decode_pnp_id(edid: bytes) -> str | None:
    if len(edid) < 10 or not edid.startswith(_EDID_HEADER):
        return None
    packed = (edid[8] << 8) | edid[9]
    letters = [(packed >> 10) & 0x1F, (packed >> 5) & 0x1F, packed & 0x1F]
    if any(v == 0 for v in letters):
        return None
    return "".join(chr(v + ord("A") - 1) for v in letters)


class DrmWatcher:
    """Polls one connector's ``dpms`` file and dispatches BLANK / UNBLANK."""

    def __init__(
        self,
        *,
        sysfs_root: str | Path = "/sys/class/drm",
        connector: str | None = None,
        poll_interval: float = 2.0,
    ) -> None:
        self.sysfs_root = Path(sysfs_root)
        self.connector = connector
        self.poll_interval = poll_interval
        self._path: Path | None = None

    # -- connector discovery ---------------------------------------------

    def resolve(self) -> Path:
        if self._path is not None:
            return self._path
        candidates = sorted(
            p for p in self.sysfs_root.glob("card*-*") if (p / "dpms").exists()
        )
        if not candidates:
            raise FileNotFoundError(
                f"no DRM connectors with a dpms node under {self.sysfs_root}"
            )
        if self.connector:
            for p in candidates:
                # directory is like "card1-HDMI-A-1"; strip the "cardN-" prefix
                if p.name.split("-", 1)[-1] == self.connector:
                    self._path = p
                    return p
            raise FileNotFoundError(
                f"configured connector {self.connector!r} not found under {self.sysfs_root}"
            )
        lg = [p for p in candidates if self._is_lg(p)]
        if len(lg) == 1:
            self._path = lg[0]
        else:
            connected = [p for p in candidates if self._is_connected(p)]
            self._path = (lg or connected or candidates)[0]
            log.warning(
                "DRM auto-detect picked %s (%d LG panel(s) found); "
                "set 'connector' in config.yaml to be explicit",
                self._path.name,
                len(lg),
            )
        return self._path

    def _is_lg(self, conn: Path) -> bool:
        try:
            edid = (conn / "edid").read_bytes()
        except OSError:
            return False
        return _decode_pnp_id(edid) in _LG_PNP_IDS

    def _is_connected(self, conn: Path) -> bool:
        try:
            return (conn / "status").read_text().strip() == "connected"
        except OSError:
            return False

    # -- polling --------------------------------------------------------

    def _read_dpms(self) -> str | None:
        try:
            return (self.resolve() / "dpms").read_text().strip()
        except OSError as exc:
            log.debug("dpms read failed: %s", exc)
            return None

    def current(self) -> str | None:
        """Best-effort snapshot of the connector's dpms state ("On"/"Off")."""
        try:
            return self._read_dpms()
        except FileNotFoundError:
            return None

    async def run(self, dispatch: Dispatch) -> None:
        path = self.resolve()
        log.info("watching DRM connector %s", path.name)
        stable = self._read_dpms() or "On"
        while True:
            await asyncio.sleep(self.poll_interval)
            cur = self._read_dpms()
            if cur is None or cur == stable:
                continue
            log.debug("dpms %s -> %s on %s", stable, cur, path.name)
            if stable == "On" and cur == "Off":
                await dispatch(Event.BLANK)
            elif stable == "Off" and cur == "On":
                await dispatch(Event.UNBLANK)
            stable = cur
