"""Session-bus fallback: org.freedesktop.ScreenSaver ActiveChanged -> BLANK/UNBLANK.

Belt-and-braces for the DRM poll: on KDE the screen-lock / screensaver path flips
this signal, and on some setups it is more reliable than the sysfs dpms node.
"""

from __future__ import annotations

import asyncio
import logging

from dbus_fast import BusType, DBusError
from dbus_fast.aio import MessageBus

from . import Dispatch, Event

log = logging.getLogger(__name__)

_SERVICE = "org.freedesktop.ScreenSaver"
_PATH = "/org/freedesktop/ScreenSaver"
_IFACE = "org.freedesktop.ScreenSaver"


class ScreenSaverWatcher:
    def __init__(self, dispatch: Dispatch) -> None:
        self._dispatch = dispatch
        self._bus: MessageBus | None = None

    async def run(self) -> None:
        self._bus = await MessageBus(bus_type=BusType.SESSION).connect()
        try:
            introspection = await self._bus.introspect(_SERVICE, _PATH)
        except DBusError:
            # No compositor provides it (e.g. Sway, or a bare Wayland session).
            # Nothing to do — return so the supervisor doesn't retry forever.
            log.warning(
                "%s is not available on the session bus; the DRM dpms poll is the "
                "only screen-off trigger here (set screensaver_dbus: false to hide "
                "this)",
                _SERVICE,
            )
            await self._bus.wait_for_disconnect()
            return
        obj = self._bus.get_proxy_object(_SERVICE, _PATH, introspection)
        iface = obj.get_interface(_IFACE)

        loop = asyncio.get_running_loop()

        def on_active_changed(active: bool) -> None:
            event = Event.BLANK if active else Event.UNBLANK
            log.info("ScreenSaver ActiveChanged(%s)", active)
            loop.create_task(self._dispatch(event))

        iface.on_active_changed(on_active_changed)
        log.info("listening for org.freedesktop.ScreenSaver ActiveChanged")
        await self._bus.wait_for_disconnect()
