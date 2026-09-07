"""webOS Companion — make an LG webOS TV follow the local display power state.

A small daemon that makes an LG WebOS TV track the local display power state on
KDE Plasma / Wayland: blank the panel when the desktop blanks the displays, and
fully power the TV off/on around system suspend and shutdown.
"""

__version__ = "0.1.0"
