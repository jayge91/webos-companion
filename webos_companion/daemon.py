"""State machine tying display events to WebOS actions.

The event -> TV-command mapping (blank -> turnOffScreen, suspend/shutdown ->
system/turnOff, resume -> Wake-on-LAN) follows the design of LGTV Companion by
Jörgen Persson (github.com/JPersson77/LGTVCompanion, MIT); see README Credits.
"""

from __future__ import annotations

import asyncio
import enum
import logging
from collections.abc import Awaitable, Callable

from .triggers import Event
from .webos import WebOsClient

log = logging.getLogger(__name__)


class State(enum.Enum):
    ON = "on"                # TV powered on, panel showing
    SCREEN_OFF = "screen_off"  # panel blanked (turnOffScreen), TV still powered
    POWERED_OFF = "powered_off"  # full system/turnOff, needs WOL to come back


class Daemon:
    def __init__(
        self,
        client: WebOsClient,
        *,
        dpms_probe: Callable[[], str | None] | None = None,
        initial_state: State = State.ON,
        action_timeout: float = 8.0,
        suspend_action_timeout: float = 2.5,
        recover_budget: float = 300.0,
    ) -> None:
        self.client = client
        self._dpms_probe = dpms_probe
        self._state = initial_state
        self._lock = asyncio.Lock()
        self._action_timeout = action_timeout
        self._suspend_action_timeout = suspend_action_timeout
        # how long to keep retrying to bring the TV back after resume/unblank
        # (the network and the TV can both take a while to come up post-wake)
        self._recover_budget = recover_budget
        self._recovery: asyncio.Task | None = None

    @property
    def state(self) -> State:
        return self._state

    async def dispatch(self, event: Event) -> None:
        async with self._lock:
            log.debug("event %s in state %s", event.name, self._state.name)
            handler = {
                Event.BLANK: self._on_blank,
                Event.UNBLANK: self._on_unblank,
                Event.SUSPEND: self._on_suspend,
                Event.RESUME: self._on_resume,
                Event.SHUTDOWN: self._on_shutdown,
            }[event]
            await handler()
            log.debug("-> state %s", self._state.name)

    async def aclose(self) -> None:
        task, self._recovery = self._recovery, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    # -- handlers -------------------------------------------------------

    async def _on_blank(self) -> None:
        self._cancel_recovery()
        if self._state is not State.ON:
            return
        log.info("display blanked -> turning the TV screen off")
        if await self._run(self.client.turn_off_screen()):
            self._state = State.SCREEN_OFF

    async def _on_unblank(self) -> None:
        self._cancel_recovery()
        if self._state is State.ON:
            return
        log.info("display on -> turning the TV screen on")
        if await self._run(self.client.ensure_on(), timeout=self._action_timeout * 3):
            await self._settle_awake()
        else:
            self._start_recovery()

    async def _on_suspend(self) -> None:
        self._cancel_recovery()
        log.info("system suspending -> powering the TV off")
        await self._run(self.client.system_off(), timeout=self._suspend_action_timeout)
        # Regardless of whether the command was ack'd, the machine is going down.
        self._state = State.POWERED_OFF

    async def _on_shutdown(self) -> None:
        self._cancel_recovery()
        log.info("system shutting down -> powering the TV off")
        await self._run(self.client.system_off(), timeout=self._suspend_action_timeout)
        self._state = State.POWERED_OFF

    async def _on_resume(self) -> None:
        self._cancel_recovery()
        log.info("system resumed -> bringing the TV back on")
        # One quick attempt (short wait for the NIC, which is usually still
        # coming up right after wake); on failure hand off to the recoverer.
        if await self._run(
            self.client.ensure_on(wol_attempts=1, network_wait=3.0),
            timeout=self._action_timeout,
        ):
            await self._settle_awake()
        else:
            self._start_recovery()

    # -- helpers -------------------------------------------------------

    async def _settle_awake(self) -> None:
        """TV is reachable and lit; match it to the desktop's current state."""
        if self._dpms_probe is not None and self._dpms_probe() == "Off":
            if await self._run(self.client.turn_off_screen()):
                self._state = State.SCREEN_OFF
                return
        self._state = State.ON

    def _start_recovery(self) -> None:
        self._cancel_recovery()
        self._recovery = asyncio.create_task(self._recover(), name="tv-recovery")

    def _cancel_recovery(self) -> None:
        if self._recovery is not None and not self._recovery.done():
            self._recovery.cancel()
        self._recovery = None

    async def _recover(self) -> None:
        """Keep trying to bring the TV online until it works or the budget runs out."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._recover_budget
        delay = 3.0
        log.info(
            "TV unreachable; retrying in the background for up to %.0fs",
            self._recover_budget,
        )
        # Don't send WOL or open sockets until the local network can route to
        # the TV (the NIC is usually still coming up right after resume).
        if not await self.client.wait_for_network(self._recover_budget):
            log.warning("network never came back; giving up on the TV")
            return
        while loop.time() < deadline:
            try:
                await asyncio.wait_for(
                    self.client.ensure_on(wol_attempts=1, wol_interval=1.5),
                    timeout=25.0,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.debug("recovery attempt failed: %s", exc)
                await asyncio.sleep(delay)
                delay = min(delay * 1.5, 8.0)
                continue
            async with self._lock:
                await self._settle_awake()
                log.info("TV recovered -> state %s", self._state.name)
            return
        log.warning("gave up bringing the TV back after %.0fs", self._recover_budget)

    async def _run(self, coro: Awaitable[object], *, timeout: float | None = None) -> bool:
        try:
            await asyncio.wait_for(coro, timeout=timeout or self._action_timeout)
            return True
        except asyncio.TimeoutError:
            log.warning("TV action timed out")
        except Exception as exc:  # never let a TV hiccup crash the daemon
            log.warning("TV action failed: %s", exc)
        return False
