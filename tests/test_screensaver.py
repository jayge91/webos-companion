"""ScreenSaver trigger against a private session bus (needs dbus-run-session)."""

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
from dbus_fast.service import ServiceInterface, signal  # noqa: E402

from webos_companion.triggers import Event  # noqa: E402
from webos_companion.triggers.screensaver import ScreenSaverWatcher  # noqa: E402


class StubScreenSaver(ServiceInterface):
    def __init__(self) -> None:
        super().__init__("org.freedesktop.ScreenSaver")

    @signal()
    def ActiveChanged(self, active: "b") -> "b":  # noqa: F821
        return active


async def test_active_changed_maps_to_blank_unblank():
    bus = await MessageBus(bus_type=BusType.SESSION).connect()
    stub = StubScreenSaver()
    bus.export("/org/freedesktop/ScreenSaver", stub)
    await bus.request_name("org.freedesktop.ScreenSaver")

    events: list[Event] = []

    async def dispatch(e: Event) -> None:
        events.append(e)

    watcher = ScreenSaverWatcher(dispatch)
    task = asyncio.create_task(watcher.run())
    try:
        await asyncio.sleep(0.3)
        stub.ActiveChanged(True)
        await asyncio.sleep(0.2)
        stub.ActiveChanged(False)
        await asyncio.sleep(0.2)
        assert events == [Event.BLANK, Event.UNBLANK]
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        bus.disconnect()


async def test_missing_interface_does_not_spin(caplog):
    # No compositor provides org.freedesktop.ScreenSaver (e.g. Sway): run() must
    # return/park rather than raise, so the supervisor doesn't retry forever.
    events: list[Event] = []

    async def dispatch(e: Event) -> None:
        events.append(e)

    watcher = ScreenSaverWatcher(dispatch)
    task = asyncio.create_task(watcher.run())
    await asyncio.sleep(0.4)
    assert not task.done() or task.exception() is None  # parked or cleanly returned
    assert "not available on the session bus" in caplog.text
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
