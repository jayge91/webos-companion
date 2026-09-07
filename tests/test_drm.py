from __future__ import annotations

import asyncio

import pytest

from webos_companion.triggers import Event
from webos_companion.triggers.drm import DrmWatcher, _decode_pnp_id
from tests.helpers import make_edid


def test_decode_pnp_id():
    assert _decode_pnp_id(make_edid("GSM")) == "GSM"
    assert _decode_pnp_id(make_edid("DEL")) == "DEL"
    assert _decode_pnp_id(b"\x00" * 128) is None


def test_resolve_autodetects_lg(drm_tree):
    root, mk = drm_tree
    mk("DP-1", vendor="DEL", status="connected")
    lg = mk("HDMI-A-1", vendor="GSM", status="connected")
    mk("HDMI-A-2", vendor="SAM", status="connected")
    w = DrmWatcher(sysfs_root=root)
    assert w.resolve() == lg


def test_resolve_explicit_connector(drm_tree):
    root, mk = drm_tree
    mk("HDMI-A-1", vendor="GSM")
    want = mk("HDMI-A-2", vendor="GSM")
    w = DrmWatcher(sysfs_root=root, connector="HDMI-A-2")
    assert w.resolve() == want


def test_resolve_explicit_missing_raises(drm_tree):
    root, mk = drm_tree
    mk("HDMI-A-1", vendor="GSM")
    with pytest.raises(FileNotFoundError):
        DrmWatcher(sysfs_root=root, connector="DP-5").resolve()


def test_resolve_no_connectors_raises(drm_tree):
    root, _ = drm_tree
    with pytest.raises(FileNotFoundError):
        DrmWatcher(sysfs_root=root).resolve()


async def _collect(w: DrmWatcher, flips, *, settle=0.08):
    events: list[Event] = []

    async def dispatch(e: Event) -> None:
        events.append(e)

    task = asyncio.create_task(w.run(dispatch))
    await asyncio.sleep(settle)
    for path, value in flips:
        (path / "dpms").write_text(value + "\n")
        await asyncio.sleep(settle)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    return events


async def test_run_emits_blank_and_unblank(drm_tree):
    root, mk = drm_tree
    conn = mk("HDMI-A-1", vendor="GSM", dpms="On")
    w = DrmWatcher(sysfs_root=root, poll_interval=0.02)
    events = await _collect(w, [(conn, "Off"), (conn, "On")])
    assert events == [Event.BLANK, Event.UNBLANK]


async def test_run_emits_on_rapid_toggle(drm_tree):
    root, mk = drm_tree
    conn = mk("HDMI-A-1", vendor="GSM", dpms="On")
    w = DrmWatcher(sysfs_root=root, poll_interval=0.02)
    events = await _collect(w, [(conn, "Off"), (conn, "On"), (conn, "Off")])
    assert events == [Event.BLANK, Event.UNBLANK, Event.BLANK]


def test_current_snapshot(drm_tree):
    root, mk = drm_tree
    mk("HDMI-A-1", vendor="GSM", dpms="Off")
    w = DrmWatcher(sysfs_root=root)
    assert w.current() == "Off"
