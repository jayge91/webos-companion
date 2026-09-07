"""Minimal async WebOS SSAP client: pair, send commands, Wake-on-LAN.

Fresh implementation, but the Wake-on-LAN retry loop and the "reconnect, then
only unblank if the panel is actually off" handling were informed by the
web_os_client.cpp of LGTV Companion by Jörgen Persson
(github.com/JPersson77/LGTVCompanion, MIT). Protocol constants live in lg_api.py.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import logging
import socket
import ssl
from collections.abc import Callable, Iterable

import websockets
from websockets.asyncio.client import ClientConnection, connect

from . import lg_api

log = logging.getLogger(__name__)

UdpSender = Callable[[bytes, Iterable[tuple[str, int]]], None]


class WebOsError(RuntimeError):
    """The TV returned an error frame or rejected pairing."""


def build_magic_packet(mac: str) -> bytes:
    """6x 0xFF followed by the 6-byte MAC repeated 16 times (102 bytes)."""
    raw = bytes.fromhex(mac.replace(":", "").replace("-", "").replace(".", ""))
    if len(raw) != 6:
        raise ValueError(f"invalid MAC address: {mac!r}")
    return b"\xff" * 6 + raw * 16


def _default_udp_sender(packet: bytes, targets: Iterable[tuple[str, int]]) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for host, port in targets:
            try:
                sock.sendto(packet, (host, port))
            except OSError as exc:  # one bad target must not stop the others
                log.debug("WOL send to %s:%s failed: %s", host, port, exc)


def route_exists(host: str) -> bool:
    """True if the kernel has *any* route toward ``host`` (no packet is sent).

    A UDP ``connect()`` only does a routing-table lookup; it raises
    ``ENETUNREACH`` when there is no route at all — the usual state for the first
    seconds after resume while the NIC is still coming up. Note a default route
    counts, so this answers "is the network stack up", not "is the TV reachable"
    (the connect + WOL retry loop settles that).
    """
    if not host:
        return False
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect((host, 9))
        finally:
            sock.close()
        return True
    except OSError:
        return False


def _insecure_ssl_context() -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


class WebOsClient:
    """One TV. Explicit :meth:`connect` / :meth:`close`; actions self-heal a dead link."""

    def __init__(
        self,
        ip: str,
        *,
        mac: str | None = None,
        client_key: str | None = None,
        use_ssl: bool = True,
        port: int | None = None,
        wol_broadcast: str = "255.255.255.255",
        on_client_key: Callable[[str], None] | None = None,
        udp_sender: UdpSender | None = None,
        pair_timeout: float = 60.0,
        route_check: Callable[[str], bool] | None = None,
    ) -> None:
        self.ip = ip
        self.mac = mac
        self.client_key = client_key
        self.use_ssl = use_ssl
        self.port = port if port is not None else (3001 if use_ssl else 3000)
        self.wol_broadcast = wol_broadcast
        self._on_client_key = on_client_key
        self._udp_sender = udp_sender or _default_udp_sender
        self._pair_timeout = pair_timeout
        self._route_check = route_check or route_exists

        self._ws: ClientConnection | None = None
        self._connected = False
        self._reader: asyncio.Task | None = None
        self._pending: dict[str, asyncio.Future[dict]] = {}
        self._register_q: asyncio.Queue[dict] = asyncio.Queue()
        self._ids = itertools.count(1)
        self._lock = asyncio.Lock()

    # -- connection ---------------------------------------------------------

    @property
    def connected(self) -> bool:
        return self._connected

    async def wait_for_network(
        self, timeout: float, *, interval: float = 0.25
    ) -> bool:
        """Block until the kernel has a route to the TV, or ``timeout`` elapses."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        announced = False
        while True:
            if self._route_check(self.ip):
                if announced:
                    log.info("network is up")
                return True
            if loop.time() >= deadline:
                return False
            if not announced:
                log.info("waiting for the network to come up before contacting the TV")
                announced = True
            await asyncio.sleep(interval)

    @property
    def url(self) -> str:
        scheme = "wss" if self.use_ssl else "ws"
        return f"{scheme}://{self.ip}:{self.port}"

    async def connect(
        self, *, pair_timeout: float | None = None, open_timeout: float | None = None
    ) -> None:
        async with self._lock:
            if self._connected:
                return
            await self._open(
                pair_timeout if pair_timeout is not None else self._pair_timeout,
                open_timeout=open_timeout,
            )

    async def _open(self, pair_timeout: float, *, open_timeout: float | None = None) -> None:
        if self._ws is not None or self._reader is not None:
            await self._teardown()  # clear a stale/closed connection first
        log.debug("connecting to %s", self.url)
        self._ws = await connect(
            self.url,
            ssl=_insecure_ssl_context() if self.use_ssl else None,
            open_timeout=open_timeout or 10,
            ping_interval=20,
            ping_timeout=20,
            max_size=2**22,
        )
        self._connected = True
        self._reader = asyncio.create_task(self._read_loop(), name="webos-reader")
        try:
            await self._handshake(pair_timeout)
        except BaseException:
            await self._teardown()
            raise
        log.info("connected and paired to %s", self.ip)

    async def close(self) -> None:
        async with self._lock:
            await self._teardown()

    async def _teardown(self) -> None:
        self._connected = False
        if self._ws is not None:
            await self._ws.close()
        reader, self._reader = self._reader, None
        if reader is not None and reader is not asyncio.current_task():
            reader.cancel()
            try:
                await asyncio.gather(reader, return_exceptions=True)
            except asyncio.CancelledError:
                pass
        self._ws = None
        self._fail_pending()

    def _fail_pending(self) -> None:
        """Reject every in-flight request; make sure the result is retrieved so
        asyncio does not warn about an unretrieved future exception."""
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(WebOsError("connection closed"))
            fut.add_done_callback(lambda f: f.cancelled() or f.exception())
        self._pending.clear()

    async def _read_loop(self) -> None:
        assert self._ws is not None
        try:
            async for raw in self._ws:
                try:
                    msg = json.loads(raw)
                except ValueError:
                    log.warning("ignoring non-JSON frame: %r", raw[:200])
                    continue
                self._dispatch(msg)
        except websockets.ConnectionClosed:
            pass
        finally:
            self._connected = False
            self._fail_pending()

    def _dispatch(self, msg: dict) -> None:
        msg_id = str(msg.get("id", ""))
        if msg_id == lg_api.REGISTER_ID:
            self._register_q.put_nowait(msg)
            return
        fut = self._pending.pop(msg_id, None)
        if fut is not None and not fut.done():
            fut.set_result(msg)

    async def _handshake(self, pair_timeout: float) -> None:
        while not self._register_q.empty():
            self._register_q.get_nowait()
        await self._ws.send(json.dumps(lg_api.register_payload(self.client_key)))
        deadline = asyncio.get_running_loop().time() + pair_timeout
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise WebOsError("timed out waiting for pairing confirmation")
            msg = await asyncio.wait_for(self._register_q.get(), timeout=remaining)
            mtype = msg.get("type")
            payload = msg.get("payload") or {}
            if mtype == "registered":
                key = payload.get("client-key")
                if key and key != self.client_key:
                    self.client_key = key
                    log.info("received new pairing key")
                    if self._on_client_key is not None:
                        self._on_client_key(key)
                return
            if mtype == "response" and (
                payload.get("pairingType") or payload.get("returnValue")
            ):
                log.info("accept the pairing prompt on the TV...")
                continue
            if mtype == "error":
                raise WebOsError(msg.get("error") or "pairing rejected")
            # anything else: keep waiting until the deadline

    async def _ensure_connected(self, *, open_timeout: float | None = None) -> None:
        if self._connected:
            return
        await self.connect(
            pair_timeout=min(self._pair_timeout, 10.0), open_timeout=open_timeout
        )

    # -- requests ---------------------------------------------------------

    async def request(
        self, uri: str, payload: dict | None = None, *, timeout: float = 5.0
    ) -> dict:
        await self._ensure_connected()
        assert self._ws is not None
        req_id = f"req_{next(self._ids)}"
        fut: asyncio.Future[dict] = asyncio.get_running_loop().create_future()
        self._pending[req_id] = fut
        try:
            await self._ws.send(json.dumps(lg_api.request(uri, payload, req_id)))
            msg = await asyncio.wait_for(fut, timeout)
        finally:
            self._pending.pop(req_id, None)
            if fut.done() and not fut.cancelled():
                fut.exception()  # retrieve, so a lost race doesn't warn
        if msg.get("type") == "error":
            raise WebOsError(msg.get("error") or f"request failed: {uri}")
        return msg.get("payload") or {}

    async def turn_off_screen(self) -> None:
        await self.request(lg_api.URI_SCREEN_OFF)

    async def turn_on_screen(self) -> None:
        await self.request(lg_api.URI_SCREEN_ON)

    async def system_off(self) -> None:
        await self.request(lg_api.URI_POWER_OFF)

    async def get_power_state(self) -> dict:
        return await self.request(lg_api.URI_GET_POWER_STATE)

    async def enable_tv_wol(self) -> None:
        """Turn on the TV's own Wake-on-LAN setting (best effort)."""
        try:
            await self.request(
                lg_api.ENABLE_WOL_REQUEST["uri"], lg_api.ENABLE_WOL_REQUEST["payload"]
            )
        except WebOsError as exc:
            log.debug("could not enable TV-side WOL: %s", exc)

    # -- power on -------------------------------------------------------

    def send_wol(self, *, quiet: bool = False) -> None:
        if not self.mac:
            log.warning("no MAC configured; cannot send Wake-on-LAN")
            return
        packet = build_magic_packet(self.mac)
        targets = [
            (self.wol_broadcast, 9), (self.ip, 9),
            (self.wol_broadcast, 7), (self.ip, 7),
        ]
        if not quiet:
            log.info("sending Wake-on-LAN to %s", self.mac)
        self._udp_sender(packet, targets)

    async def send_wol_burst(self, count: int = 5, spacing: float = 0.2) -> None:
        """A short burst of magic packets — a single one can be dropped while the
        switch port is still coming up right after a resume."""
        if not self.mac:
            log.warning("no MAC configured; cannot send Wake-on-LAN")
            return
        log.info("sending Wake-on-LAN to %s (burst of %d)", self.mac, count)
        for i in range(count):
            self.send_wol(quiet=True)
            if i + 1 < count:
                await asyncio.sleep(spacing)

    # states in which the panel is already lit — no turnOnScreen needed
    _AWAKE_STATES = frozenset({"Active", "Screen On", "Power On", ""})

    async def ensure_on(
        self,
        *,
        allow_wol: bool = True,
        wol_attempts: int = 10,
        wol_interval: float = 2.0,
        network_wait: float = 0.0,
        force_unblank: bool = False,
        connect_timeout: float | None = None,
    ) -> None:
        """Bring the TV to a usable state: reconnect if needed, WOL if off, unblank.

        With ``network_wait`` > 0, first wait that many seconds for the local
        network to be routable — no WOL or socket attempt is made before then.
        With ``force_unblank`` the panel is unblanked once the TV is reachable
        even if it reports an awake state (a TV woken from standby often reports
        ``Active`` for a moment while the screen is still black).
        """
        if network_wait and not await self.wait_for_network(network_wait):
            raise ConnectionError(f"no route to {self.ip} (network still down)")
        if await self._try_reach(force_unblank=force_unblank, connect_timeout=connect_timeout):
            return
        if allow_wol and self.mac:
            for attempt in range(1, wol_attempts + 1):
                await self.send_wol_burst()
                await asyncio.sleep(wol_interval)
                if await self._try_reach(
                    force_unblank=force_unblank, connect_timeout=connect_timeout
                ):
                    return
                log.debug("TV still unreachable after WOL attempt %d", attempt)
        raise ConnectionError(f"could not bring TV {self.ip} online")

    async def _try_reach(
        self, *, force_unblank: bool = False, connect_timeout: float | None = None
    ) -> bool:
        """True once the TV answers on the socket; unblank the panel if it's dark."""
        try:
            await self._ensure_connected(open_timeout=connect_timeout)
        except Exception as exc:  # noqa: BLE001  (any failure => not reachable yet)
            log.debug("connect attempt failed: %r", exc)
            self._connected = False
            return False
        try:
            state = (await self.get_power_state()).get("state", "")
        except (WebOsError, OSError) as exc:
            log.debug("power-state read after reconnect failed: %r", exc)
            state = ""
        # Normally only unblank when the TV says it is off — turnOnScreen on an
        # already-lit panel returns "500 Application error". ``force_unblank``
        # skips the check (a just-woken TV reports "Active" while still black).
        if force_unblank or state not in self._AWAKE_STATES:
            log.debug("unblank after reconnect (power state %r, force=%s)", state, force_unblank)
            await self._unblank_resilient()
        else:
            log.debug("panel reported already lit (power state %r)", state)
        return True

    async def _unblank_resilient(self, tries: int = 3, delay: float = 1.5) -> None:
        """turnOnScreen, retrying — a freshly-woken TV often drops the socket
        mid-call for the first few seconds. ``turn_on_screen`` reconnects on the
        next attempt via ``_ensure_connected``."""
        for i in range(1, tries + 1):
            try:
                await self.turn_on_screen()
                return
            except WebOsError as exc:
                if "500" in str(exc):  # already lit — nothing to do
                    log.debug("turnOnScreen: panel already on")
                    return
                log.debug("turnOnScreen attempt %d/%d: %r", i, tries, exc)
            except OSError as exc:
                log.debug("turnOnScreen attempt %d/%d: %r", i, tries, exc)
            if i < tries:
                await asyncio.sleep(delay)
