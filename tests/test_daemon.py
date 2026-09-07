from __future__ import annotations

import asyncio

from webos_companion.daemon import Daemon, State
from webos_companion.triggers import Event


class StubClient:
    def __init__(self, *, fail: set[str] | None = None, network_up: bool = True) -> None:
        self.calls: list[str] = []
        self.fail = fail or set()
        self.network_up = network_up
        self.mac = "aa:bb:cc:dd:ee:ff"

    async def wait_for_network(self, timeout, **kw) -> bool:
        return self.network_up

    async def send_wol_burst(self, **kw) -> None:
        pass  # WoL bursting is exercised in test_webos.py, not here

    async def _do(self, name: str) -> None:
        self.calls.append(name)
        if name in self.fail:
            raise RuntimeError(f"{name} boom")

    async def turn_off_screen(self) -> None:
        await self._do("off")

    async def turn_on_screen(self) -> None:
        await self._do("on")

    async def system_off(self) -> None:
        await self._do("system_off")

    async def ensure_on(self, **kw) -> None:
        await self._do("ensure_on")


def _daemon(client, *, dpms="On", state=State.ON, recover_budget=5.0):
    return Daemon(
        client,
        dpms_probe=lambda: dpms,
        initial_state=state,
        recover_budget=recover_budget,
    )


async def test_blank_from_on():
    c = StubClient()
    d = _daemon(c)
    await d.dispatch(Event.BLANK)
    assert c.calls == ["off"]
    assert d.state is State.SCREEN_OFF


async def test_blank_is_idempotent():
    c = StubClient()
    d = _daemon(c)
    await d.dispatch(Event.BLANK)
    await d.dispatch(Event.BLANK)
    assert c.calls == ["off"]


async def test_unblank_from_screen_off():
    c = StubClient()
    d = _daemon(c, state=State.SCREEN_OFF)
    await d.dispatch(Event.UNBLANK)
    assert c.calls == ["ensure_on"]
    assert d.state is State.ON


async def test_unblank_ignored_when_on():
    c = StubClient()
    d = _daemon(c, state=State.ON)
    await d.dispatch(Event.UNBLANK)
    assert c.calls == []


async def test_suspend_powers_off():
    c = StubClient()
    d = _daemon(c)
    await d.dispatch(Event.SUSPEND)
    assert c.calls == ["system_off"]
    assert d.state is State.POWERED_OFF


async def test_shutdown_powers_off():
    c = StubClient()
    d = _daemon(c, state=State.SCREEN_OFF)
    await d.dispatch(Event.SHUTDOWN)
    assert c.calls == ["system_off"]
    assert d.state is State.POWERED_OFF


async def test_resume_to_lit_screen():
    c = StubClient()
    d = _daemon(c, dpms="On", state=State.POWERED_OFF)
    await d.dispatch(Event.RESUME)
    # resume always hands off to the background recoverer now
    await asyncio.wait_for(d._recovery, timeout=5)
    assert c.calls == ["ensure_on"]
    assert d.state is State.ON


async def test_resume_into_still_blanked_screen():
    c = StubClient()
    d = _daemon(c, dpms="Off", state=State.POWERED_OFF)
    await d.dispatch(Event.RESUME)
    await asyncio.wait_for(d._recovery, timeout=5)
    assert c.calls == ["ensure_on", "off"]
    assert d.state is State.SCREEN_OFF


async def test_failed_blank_keeps_state():
    c = StubClient(fail={"off"})
    d = _daemon(c)
    await d.dispatch(Event.BLANK)
    assert d.state is State.ON  # not advanced on failure


async def test_suspend_advances_even_if_command_fails():
    c = StubClient(fail={"system_off"})
    d = _daemon(c)
    await d.dispatch(Event.SUSPEND)
    assert d.state is State.POWERED_OFF  # machine is going down regardless


async def test_dispatch_serialises_concurrent_events():
    c = StubClient()
    d = _daemon(c)
    await asyncio.gather(
        d.dispatch(Event.BLANK),
        d.dispatch(Event.UNBLANK),
    )
    # Whatever the interleaving, calls happen one full handler at a time.
    assert c.calls in (["off", "ensure_on"], ["off"])
    await d.aclose()


async def test_resume_failure_starts_recovery_that_later_succeeds():
    c = StubClient(fail={"ensure_on"})
    d = _daemon(c, state=State.POWERED_OFF)
    await d.dispatch(Event.RESUME)
    # still powered-off, recovery running in the background
    assert d.state is State.POWERED_OFF
    assert d._recovery is not None and not d._recovery.done()

    c.fail.discard("ensure_on")  # TV comes back
    await asyncio.wait_for(d._recovery, timeout=5)
    assert d.state is State.ON


async def test_suspend_cancels_running_recovery():
    c = StubClient(fail={"ensure_on"})
    d = _daemon(c, state=State.POWERED_OFF)
    await d.dispatch(Event.RESUME)
    recovery = d._recovery
    assert recovery is not None

    await d.dispatch(Event.SUSPEND)
    await asyncio.sleep(0)
    assert recovery.cancelled() or recovery.done()
    assert d.state is State.POWERED_OFF
    await d.aclose()


async def test_aclose_stops_recovery():
    c = StubClient(fail={"ensure_on"})
    d = _daemon(c, state=State.POWERED_OFF)
    await d.dispatch(Event.RESUME)
    assert d._recovery is not None
    await d.aclose()
    assert d._recovery is None


async def test_unblank_failure_starts_recovery():
    c = StubClient(fail={"ensure_on"})
    d = _daemon(c, state=State.SCREEN_OFF)
    await d.dispatch(Event.UNBLANK)
    assert d.state is State.SCREEN_OFF
    assert d._recovery is not None and not d._recovery.done()
    await d.aclose()


async def test_unblank_while_powered_off_goes_to_recovery():
    c = StubClient(fail={"ensure_on"})
    d = _daemon(c, state=State.POWERED_OFF)
    await d.dispatch(Event.UNBLANK)
    # no inline ensure_on — straight to the WoL recovery path
    assert "ensure_on" not in c.calls
    assert d._recovery is not None and not d._recovery.done()
    await d.aclose()


async def test_unblank_does_not_disturb_a_running_recovery():
    c = StubClient(fail={"ensure_on"})
    d = _daemon(c, state=State.POWERED_OFF)
    await d.dispatch(Event.RESUME)
    recovery = d._recovery
    assert recovery is not None
    await d.dispatch(Event.UNBLANK)  # the DRM trigger also fires on resume
    assert d._recovery is recovery  # same task, not replaced
    await d.aclose()


async def test_recovery_gives_up_if_network_never_returns():
    c = StubClient(fail={"ensure_on"}, network_up=False)
    d = _daemon(c, state=State.POWERED_OFF)
    await d.dispatch(Event.RESUME)
    assert d._recovery is not None
    await asyncio.wait_for(d._recovery, timeout=2)
    # never even attempted to reach the TV
    assert "ensure_on" not in c.calls
    assert d.state is State.POWERED_OFF
