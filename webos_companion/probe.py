"""Read-only host diagnostics: DRM state, logind, ScreenSaver, TV reachability.

Nothing here mutates anything — no inhibitors are held, no power commands are
sent. Used to validate the host wiring before running the real daemon.
"""

from __future__ import annotations

import asyncio
import contextlib

from .config import Config
from .triggers.drm import DrmWatcher, _decode_pnp_id


def _drm_report(cfg: Config) -> None:
    print("== DRM connectors ==")
    watcher = DrmWatcher(connector=cfg.connector or None)
    root = watcher.sysfs_root
    conns = sorted(p for p in root.glob("card*-*") if (p / "dpms").exists())
    if not conns:
        print(f"  (none with a dpms node under {root})")
        return

    try:
        chosen = watcher.resolve()
    except FileNotFoundError as exc:
        chosen = None
        print(f"  connector selection failed: {exc}")

    for p in conns:
        try:
            status = (p / "status").read_text().strip()
        except OSError:
            status = "?"
        try:
            dpms = (p / "dpms").read_text().strip()
        except OSError:
            dpms = "?"
        vendor = "?"
        with contextlib.suppress(OSError):
            vendor = _decode_pnp_id((p / "edid").read_bytes()) or "-"
        mark = "  <- watched" if p == chosen else ""
        print(f"  {p.name:<22} status={status:<12} dpms={dpms:<4} edid_vendor={vendor}{mark}")


async def _logind_report() -> None:
    print("\n== logind (system bus) ==")
    try:
        from dbus_fast import BusType
        from dbus_fast.aio import MessageBus

        bus = await MessageBus(bus_type=BusType.SYSTEM, negotiate_unix_fd=True).connect()
        intro = await bus.introspect("org.freedesktop.login1", "/org/freedesktop/login1")
        mgr = bus.get_proxy_object(
            "org.freedesktop.login1", "/org/freedesktop/login1", intro
        ).get_interface("org.freedesktop.login1.Manager")
        inhibitors = await mgr.call_list_inhibitors()
        print(f"  connected OK; {len(inhibitors)} inhibitor(s) currently held:")
        for what, who, why, mode, uid, pid in inhibitors:
            print(f"    [{mode}] {what:<20} {who} (uid={uid} pid={pid}) — {why}")
        bus.disconnect()
    except Exception as exc:  # noqa: BLE001
        print(f"  FAILED: {exc}")


async def _screensaver_report() -> None:
    print("\n== org.freedesktop.ScreenSaver (session bus) ==")
    try:
        from dbus_fast import BusType
        from dbus_fast.aio import MessageBus

        bus = await MessageBus(bus_type=BusType.SESSION).connect()
        intro = await bus.introspect(
            "org.freedesktop.ScreenSaver", "/org/freedesktop/ScreenSaver"
        )
        iface = bus.get_proxy_object(
            "org.freedesktop.ScreenSaver", "/org/freedesktop/ScreenSaver", intro
        ).get_interface("org.freedesktop.ScreenSaver")
        try:
            active = await iface.call_get_active()
            print(f"  connected OK; GetActive={active}")
        except Exception as exc:  # noqa: BLE001
            print(f"  connected OK; GetActive unavailable ({exc})")
        try:
            idle = await iface.call_get_session_idle_time()
            print(f"  SessionIdleTime={idle}ms")
        except Exception:  # noqa: BLE001
            pass
        print("  (the daemon only needs the ActiveChanged signal, not these getters)")
        bus.disconnect()
    except Exception as exc:  # noqa: BLE001
        print(f"  FAILED to connect: {exc}")


async def _tv_report(cfg: Config) -> None:
    print("\n== TV (read-only) ==")
    from .config import load_client_key
    from .webos import WebOsClient, WebOsError

    client = WebOsClient(
        cfg.ip,
        mac=cfg.mac or None,
        client_key=load_client_key(),
        use_ssl=cfg.ssl,
        port=cfg.port or None,
    )
    try:
        await client.connect(pair_timeout=10)
        state = await client.get_power_state()
        print(f"  {cfg.ip}: reachable, paired={'yes' if client.client_key else 'no'}")
        print(f"  power state: {state}")
    except (OSError, WebOsError, asyncio.TimeoutError) as exc:
        print(f"  {cfg.ip}: unreachable ({exc})")
    finally:
        await client.close()


async def run_probe(cfg: Config) -> int:
    _drm_report(cfg)
    await _logind_report()
    await _screensaver_report()
    if cfg.ip:
        await _tv_report(cfg)
    else:
        print("\n== TV ==\n  (no ip in config; skipping)")
    return 0
