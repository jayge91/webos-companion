"""Command-line entry point: setup | discover | pair | on | off | status | probe | service | run."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from . import __version__, discover, net, service
from .config import Config, config_path, load_client_key, save_client_key
from .daemon import Daemon
from .triggers.drm import DrmWatcher
from .webos import WebOsClient, WebOsError

log = logging.getLogger("webos_companion")


def _make_client(cfg: Config) -> WebOsClient:
    return WebOsClient(
        cfg.ip,
        mac=cfg.mac or None,
        client_key=load_client_key(),
        use_ssl=cfg.ssl,
        port=cfg.port or None,
        wol_broadcast=cfg.wol_broadcast,
        on_client_key=save_client_key,
    )


# -- interactive setup -------------------------------------------------------


def _ask(label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        answer = input(f"{label}{suffix}: ").strip()
    except EOFError:
        answer = ""
    return answer or default


def _ask_yes_no(label: str, *, default: bool) -> bool:
    hint = "Y/n" if default else "y/N"
    try:
        answer = input(f"{label} [{hint}]: ").strip().lower()
    except EOFError:
        return default
    if not answer:
        return default
    return answer[0] == "y"


def _choose_tv(candidates: list, current_ip: str) -> tuple[str, str | None]:
    """Present the discovered TVs and return the chosen (ip, mac-or-None)."""
    if candidates:
        print(f"\nFound {len(candidates)} device(s):\n")
        for i, c in enumerate(candidates, 1):
            print(f"  {i}) {c.describe()}")
        print()
        default = current_ip or "1"
        while True:
            answer = _ask("Choose a number, or type the TV's IP address", default)
            if answer.isdigit() and 1 <= int(answer) <= len(candidates):
                chosen = candidates[int(answer) - 1]
                return chosen.ip, chosen.mac
            if net.looks_like_ipv4(answer):
                for c in candidates:
                    if c.ip == answer:
                        return c.ip, c.mac
                return answer, net.neigh_mac(answer)
            print("  please enter one of the list numbers, or an IPv4 address")
    print("\nNo TVs found automatically.")
    ip = _ask("TV IP address", current_ip)
    return ip, (net.neigh_mac(ip) if ip else None)


def _detect_connector() -> str:
    try:
        name = DrmWatcher().resolve().name  # e.g. "card1-HDMI-A-1"
        return name.split("-", 1)[-1]
    except (FileNotFoundError, OSError):
        return ""


async def _cmd_setup(cfg: Config) -> int:
    if not sys.stdin.isatty():
        print("setup is interactive; run it in a terminal", file=sys.stderr)
        return 2

    print("webOS Companion — setup\n")
    existing = config_path().exists()
    if existing and not _ask_yes_no(
        f"Config already exists at {config_path()} — reconfigure it?", default=False
    ):
        print("Keeping the existing configuration.")
    else:
        print("Scanning the network for LG TVs (a few seconds)...")
        candidates = await asyncio.to_thread(discover.discover)
        ip, found_mac = _choose_tv(candidates, cfg.ip)
        if not ip:
            print("An IP address is required.", file=sys.stderr)
            return 2
        if not net.ping(ip):
            print(f"  note: {ip} did not respond to ping (continuing anyway)")

        mac = cfg.mac or found_mac or net.neigh_mac(ip) or ""
        if mac:
            print(f"  MAC address: {mac}")
        mac = _ask("TV MAC address (for Wake-on-LAN on resume)", mac)

        detected = _detect_connector()
        if detected:
            print(f"  detected the LG panel on connector {detected}")
        connector = _ask(
            "DRM connector (blank = auto-detect)", cfg.connector or ""
        )

        new = Config(ip=ip, mac=mac.lower(), connector=connector)
        new.validate()
        new.save()
        cfg = new
        print(f"\n  wrote {config_path()}\n")

    if not load_client_key() or _ask_yes_no("Pair with the TV now?", default=not load_client_key()):
        print()
        if await _cmd_pair(cfg) != 0:
            return 1

    print()
    if _ask_yes_no(
        "Install and start the background service (runs on login)?", default=True
    ):
        try:
            service.install()
            print(f"  service: {service.status_text()}")
        except (RuntimeError, OSError) as exc:
            print(f"  service install failed: {exc}", file=sys.stderr)
            print("  you can retry with: webos-companion service install")

    print("\nAll set. Check anytime with:  webos-companion status")
    return 0


def _cmd_service(action: str) -> int:
    try:
        if action == "install":
            service.install()
        elif action == "remove":
            service.remove()
        print(f"service: {service.status_text()}")
        return 0
    except (RuntimeError, OSError) as exc:
        print(f"service {action} failed: {exc}", file=sys.stderr)
        return 1


async def _cmd_pair(cfg: Config) -> int:
    client = _make_client(cfg)
    print(f"Connecting to {cfg.ip} — accept the pairing prompt on the TV...")
    try:
        await client.connect(pair_timeout=90)
    except (OSError, WebOsError, asyncio.TimeoutError) as exc:
        print(f"Pairing failed: {exc}", file=sys.stderr)
        return 1
    print("Paired. Key saved.")

    if not cfg.mac:
        mac = net.neigh_mac(cfg.ip)
        if mac:
            cfg.mac = mac
            cfg.save()
            print(f"Saved TV MAC {mac} for Wake-on-LAN.")
        else:
            print(
                "Could not read the TV's MAC from the ARP table; set 'mac' in "
                f"{config_path()} manually for Wake-on-LAN on resume."
            )
    await client.enable_tv_wol()
    await client.close()
    return 0


async def _cmd_discover() -> int:
    print("Scanning the network for LG TVs (a few seconds)...")
    candidates = await asyncio.to_thread(discover.discover)
    if not candidates:
        print("No TVs found.")
        return 1
    for c in candidates:
        print(f"  {c.describe()}")
    return 0


async def _cmd_simple(cfg: Config, action: str) -> int:
    client = _make_client(cfg)
    try:
        await client.connect(pair_timeout=10)
        if action == "on":
            await client.turn_on_screen()
        else:
            await client.turn_off_screen()
    except (OSError, WebOsError, asyncio.TimeoutError) as exc:
        print(f"{action} failed: {exc}", file=sys.stderr)
        return 1
    finally:
        await client.close()
    print(f"screen {action}")
    return 0


async def _cmd_status(cfg: Config) -> int:
    drm = DrmWatcher(connector=cfg.connector or None, poll_interval=cfg.poll_interval)
    try:
        connector = drm.resolve().name
        dpms = drm.current()
    except FileNotFoundError as exc:
        connector, dpms = f"(none: {exc})", None

    client = _make_client(cfg)
    power = "unreachable"
    try:
        await client.connect(pair_timeout=10)
        power = (await client.get_power_state()).get("state", "unknown")
    except (OSError, WebOsError, asyncio.TimeoutError) as exc:
        power = f"unreachable ({exc})"
    finally:
        await client.close()

    print(f"config:     {config_path()}")
    print(f"tv:         {cfg.ip}  mac={cfg.mac or '-'}  ssl={cfg.ssl}")
    print(f"paired:     {'yes' if load_client_key() else 'no'}")
    print(f"connector:  {connector}  dpms={dpms}")
    print(f"tv power:   {power}")
    print(f"service:    {service.status_text()}")
    return 0


class _DryRunClient(WebOsClient):
    """Connects and reads state for real, but logs mutating calls instead of sending."""

    async def turn_off_screen(self) -> None:
        log.info("[dry-run] would turn the TV screen OFF")

    async def turn_on_screen(self) -> None:
        log.info("[dry-run] would turn the TV screen ON")

    async def system_off(self) -> None:
        log.info("[dry-run] would power the TV OFF (system/turnOff)")

    async def ensure_on(self, **kw) -> None:
        log.info("[dry-run] would bring the TV back on (reconnect / WOL / unblank)")

    def send_wol(self) -> None:
        log.info("[dry-run] would send Wake-on-LAN to %s", self.mac)


async def _cmd_run(cfg: Config, *, dry_run: bool = False, seconds: float | None = None) -> int:
    drm = DrmWatcher(
        connector=cfg.connector or None,
        poll_interval=cfg.poll_interval,
    )
    factory = _DryRunClient if dry_run else WebOsClient
    client = factory(
        cfg.ip,
        mac=cfg.mac or None,
        client_key=load_client_key(),
        use_ssl=cfg.ssl,
        port=cfg.port or None,
        wol_broadcast=cfg.wol_broadcast,
        on_client_key=None if dry_run else save_client_key,
    )
    daemon = Daemon(client, dpms_probe=drm.current)
    if dry_run:
        log.info("dry-run: display events will be logged, the TV will not be touched")

    if not cfg.ip:
        log.warning("no 'ip' in config — running display-event watch only")
    else:
        try:
            await client.wait_for_network(15)
            await client.connect(pair_timeout=10)
            log.info("connected to TV at %s", cfg.ip)
        except Exception as exc:  # noqa: BLE001
            log.warning("TV not reachable at startup (%s); will connect on demand", exc)

    def logind_factory():
        from .triggers.logind import LogindWatcher

        return LogindWatcher(daemon.dispatch, passive=dry_run).run()

    def screensaver_factory():
        from .triggers.screensaver import ScreenSaverWatcher

        return ScreenSaverWatcher(daemon.dispatch).run()

    factories = [
        ("drm", lambda: drm.run(daemon.dispatch)),
        ("logind", logind_factory),
    ]
    if cfg.screensaver_dbus:
        factories.append(("screensaver", screensaver_factory))

    tasks = [asyncio.create_task(_supervise(name, f)) for name, f in factories]
    try:
        if seconds is not None:
            log.info("watching for %.0fs...", seconds)
            await asyncio.wait_for(asyncio.gather(*tasks), timeout=seconds)
        else:
            await asyncio.gather(*tasks)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await daemon.aclose()
        await client.close()
    return 0


async def _run_probe(cfg: Config) -> int:
    from .probe import run_probe

    return await run_probe(cfg)


async def _supervise(name: str, factory) -> None:
    delay = 2.0
    while True:
        try:
            await factory()
            return
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.error("%s trigger crashed: %s; retrying in %.0fs", name, exc, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60.0)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        default=argparse.SUPPRESS,
        help="debug logging",
    )

    p = argparse.ArgumentParser(
        prog="webos-companion", description=__doc__, parents=[common]
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="command", required=True)
    for name, help_text in [
        ("setup", "interactive first-time setup (config, pairing, service)"),
        ("discover", "scan the network and list LG TVs"),
        ("pair", "pair with the TV and store the key"),
        ("on", "turn the TV screen on"),
        ("off", "turn the TV screen off"),
        ("status", "show configuration and current state"),
        ("probe", "read-only host diagnostics (DRM, logind, ScreenSaver, TV)"),
    ]:
        sub.add_parser(name, help=help_text, parents=[common])
    svc = sub.add_parser("service", help="install / remove the background service", parents=[common])
    svc.add_argument("action", choices=["install", "remove", "status"])
    run = sub.add_parser("run", help="run the daemon", parents=[common])
    run.add_argument(
        "--dry-run",
        action="store_true",
        help="log display events but never touch the TV",
    )
    run.add_argument(
        "--seconds",
        type=float,
        default=None,
        help="exit after N seconds (for a bounded test)",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if getattr(args, "verbose", False) else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    # These are far too chatty at DEBUG and drown out our own events.
    for noisy in ("websockets", "websockets.client", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.INFO)

    if args.command == "service":
        return _cmd_service(args.action)
    if args.command == "discover":
        return asyncio.run(_cmd_discover())

    cfg = Config.load()
    needs_config = args.command not in ("probe", "setup") and not (
        args.command == "run" and args.dry_run
    )
    if needs_config:
        try:
            cfg.validate()
        except ValueError as exc:
            print(f"config error: {exc}", file=sys.stderr)
            if not config_path().exists():
                print("run  webos-companion setup  to create it", file=sys.stderr)
            return 2

    runner = {
        "setup": lambda: _cmd_setup(cfg),
        "pair": lambda: _cmd_pair(cfg),
        "on": lambda: _cmd_simple(cfg, "on"),
        "off": lambda: _cmd_simple(cfg, "off"),
        "status": lambda: _cmd_status(cfg),
        "probe": lambda: _run_probe(cfg),
        "run": lambda: _cmd_run(cfg, dry_run=args.dry_run, seconds=args.seconds),
    }[args.command]

    try:
        return asyncio.run(runner())
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
