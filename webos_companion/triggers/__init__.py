"""Event sources that tell the daemon what the local displays are doing."""

from __future__ import annotations

import enum
from collections.abc import Awaitable, Callable


class Event(enum.Enum):
    BLANK = "blank"          # desktop turned the displays off (energy saving / DPMS)
    UNBLANK = "unblank"      # desktop turned the displays back on
    SUSPEND = "suspend"      # system is going to sleep
    RESUME = "resume"        # system woke up
    SHUTDOWN = "shutdown"    # system is powering down / rebooting


# A trigger calls this and awaits until the daemon has finished reacting.
Dispatch = Callable[[Event], Awaitable[None]]
