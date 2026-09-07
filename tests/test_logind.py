"""logind trigger against a private session bus.

Run under a bus, e.g.:  dbus-run-session -- pytest tests/test_logind.py
Skipped automatically when no session bus is available.
"""

from __future__ import annotations

import asyncio
import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("DBUS_SESSION_BUS_ADDRESS"),
    reason="needs a session bus (run under dbus-run-session)",
)

from dbus_fast import BusType  # noqa: E402
from dbus_fast.aio import MessageBus  # noqa: E402
from dbus_fast.service import ServiceInterface, method, signal  # noqa: E402

from webos_companion.triggers import Event  # noqa: E402
from webos_companion.triggers.logind import LogindWatcher  # noqa: E402


class StubLogind(ServiceInterface):
    def __init__(self) -> None:
        super().__init__("org.freedesktop.login1.Manager")
        self.inhibits = 0
        self._fds: list[int] = []

    @method()
    def Inhibit(self, what: "s", who: "s", why: "s", mode: "s") -> "h":  # noqa: F821
        self.inhibits += 1
        r, w = os.pipe()
        self._fds += [r, w]
        return w

    @signal()
    def PrepareForSleep(self, start: "b") -> "b":  # noqa: F821
        return start

    @signal()
    def PrepareForShutdown(self, start: "b") -> "b":  # noqa: F821
        return start

    def cleanup(self) -> None:
        for fd in self._fds:
            try:
                os.close(fd)
            except OSError:
                pass


async def test_sleep_resume_shutdown_cycle():
    bus = await MessageBus(bus_type=BusType.SESSION, negotiate_unix_fd=True).connect()
    stub = StubLogind()
    bus.export("/org/freedesktop/login1", stub)
    await bus.request_name("org.freedesktop.login1")

    events: list[Event] = []

    async def dispatch(e: Event) -> None:
        events.append(e)

    watcher = LogindWatcher(dispatch, bus_type=BusType.SESSION)
    task = asyncio.create_task(watcher.run())
    try:
        await asyncio.sleep(0.3)
        assert stub.inhibits == 1  # delay inhibitor taken at startup

        stub.PrepareForSleep(True)
        await asyncio.sleep(0.3)
        assert events == [Event.SUSPEND]

        stub.PrepareForSleep(False)
        await asyncio.sleep(0.3)
        assert events == [Event.SUSPEND, Event.RESUME]
        assert stub.inhibits == 2  # re-acquired after resume

        stub.PrepareForShutdown(True)
        await asyncio.sleep(0.3)
        assert events == [Event.SUSPEND, Event.RESUME, Event.SHUTDOWN]
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        stub.cleanup()
        bus.disconnect()


async def test_handler_bounded_by_timeout():
    bus = await MessageBus(bus_type=BusType.SESSION, negotiate_unix_fd=True).connect()
    stub = StubLogind()
    bus.export("/org/freedesktop/login1", stub)
    await bus.request_name("org.freedesktop.login1")

    async def slow_dispatch(e: Event) -> None:
        await asyncio.sleep(5)

    watcher = LogindWatcher(slow_dispatch, bus_type=BusType.SESSION, handled_timeout=0.2)
    task = asyncio.create_task(watcher.run())
    try:
        await asyncio.sleep(0.3)
        stub.PrepareForSleep(True)
        # Should return promptly and release the inhibitor despite the slow handler.
        await asyncio.sleep(0.6)
        assert watcher._inhibitor_fd is None
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        stub.cleanup()
        bus.disconnect()
