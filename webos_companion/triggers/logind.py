"""systemd-logind triggers: PrepareForSleep / PrepareForShutdown + a delay inhibitor.

The delay inhibitor buys us a few seconds (logind's InhibitDelayMaxSec, 5s by
default) between the signal and the machine actually sleeping, so the TV can be
powered off first.
"""

from __future__ import annotations

import asyncio
import logging
import os

from dbus_fast import BusType
from dbus_fast.aio import MessageBus

from . import Dispatch, Event

log = logging.getLogger(__name__)

_SERVICE = "org.freedesktop.login1"
_PATH = "/org/freedesktop/login1"
_IFACE = "org.freedesktop.login1.Manager"


class LogindWatcher:
    def __init__(
        self,
        dispatch: Dispatch,
        *,
        handled_timeout: float = 3.0,
        bus_type: BusType = BusType.SYSTEM,
        passive: bool = False,
    ) -> None:
        self._dispatch = dispatch
        self._handled_timeout = handled_timeout
        self._bus_type = bus_type
        # passive: listen to signals only, never hold a delay inhibitor
        # (used by `run --dry-run` so the host is left completely untouched).
        self._passive = passive
        self._bus: MessageBus | None = None
        self._manager = None
        self._inhibitor_fd: int | None = None

    async def run(self) -> None:
        self._bus = await MessageBus(
            bus_type=self._bus_type, negotiate_unix_fd=True
        ).connect()
        introspection = await self._bus.introspect(_SERVICE, _PATH)
        obj = self._bus.get_proxy_object(_SERVICE, _PATH, introspection)
        self._manager = obj.get_interface(_IFACE)

        loop = asyncio.get_running_loop()
        self._manager.on_prepare_for_sleep(
            lambda start: loop.create_task(self._on_sleep(bool(start)))
        )
        self._manager.on_prepare_for_shutdown(
            lambda start: loop.create_task(self._on_shutdown(bool(start)))
        )
        await self._acquire_inhibitor()
        log.info("listening for logind PrepareForSleep / PrepareForShutdown")
        try:
            await self._bus.wait_for_disconnect()
        finally:
            self._release_inhibitor()

    async def _acquire_inhibitor(self) -> None:
        if self._passive or self._inhibitor_fd is not None or self._manager is None:
            return
        fd = await self._manager.call_inhibit(
            "sleep:shutdown",
            "webos-companion",
            "Turn the TV off before sleep/shutdown",
            "delay",
        )
        self._inhibitor_fd = int(fd)
        log.debug("acquired logind delay inhibitor (fd=%s)", self._inhibitor_fd)

    def _release_inhibitor(self) -> None:
        if self._inhibitor_fd is None:
            return
        try:
            os.close(self._inhibitor_fd)
        except OSError:
            pass
        log.debug("released logind delay inhibitor")
        self._inhibitor_fd = None

    async def _on_sleep(self, start: bool) -> None:
        if start:
            await self._handle_bounded(Event.SUSPEND)
            self._release_inhibitor()
        else:
            await self._dispatch(Event.RESUME)
            await self._acquire_inhibitor()

    async def _on_shutdown(self, start: bool) -> None:
        if start:
            await self._handle_bounded(Event.SHUTDOWN)
            self._release_inhibitor()

    async def _handle_bounded(self, event: Event) -> None:
        try:
            await asyncio.wait_for(
                self._dispatch(event), timeout=self._handled_timeout
            )
        except asyncio.TimeoutError:
            log.warning(
                "%s handling exceeded %.1fs; continuing so the system is not held up",
                event.name,
                self._handled_timeout,
            )
