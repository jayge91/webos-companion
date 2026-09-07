"""Find LG WebOS TVs on the local network (SSDP + SSAP-port probe)."""

from __future__ import annotations

import plistlib
import socket
import ssl
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from . import net

_SSDP_ADDR = ("239.255.255.250", 1900)
_SSAP_PORTS = (3001, 3000)
_WEBOS_HINTS = ("webos", "lge", "lg electronics", "lg smart", "lg-tv")

# A few LG Electronics MAC OUI prefixes — only used to add a hint label.
_LG_OUIS = {
    "00:1c:62", "00:1e:75", "00:1f:6b", "00:22:a9", "00:24:83", "00:25:e5",
    "00:26:e2", "00:aa:70", "00:e0:91", "08:d4:6a", "10:68:3f", "10:f1:f2",
    "2c:54:cf", "2c:59:8a", "34:4d:f7", "38:8c:50", "3c:bd:d8", "40:b0:fa",
    "48:59:29", "50:55:27", "58:a2:b5", "64:bc:0c", "6c:dd:bc", "70:91:f3",
    "74:a5:28", "7c:1c:4e", "80:5b:65", "88:36:6c", "8c:3c:4a", "a8:16:b2",
    "a8:23:fe", "b0:37:95", "b4:e6:2a", "c4:36:6c", "c4:9a:02", "cc:2d:8c",
    "dc:0b:34", "e8:5b:5b", "e8:f2:e2", "f8:0c:f3",
}


@dataclass
class TvCandidate:
    ip: str
    mac: str | None = None
    name: str = ""                 # friendly name the TV shares (AirPlay, else mDNS/PTR)
    model: str = ""                # model number, e.g. "OLED42C2PUA" (AirPlay)
    ssap_port: int | None = None   # open SSAP port (3001/3000), if any
    webos: bool = False            # confirmed LG webOS (AirPlay/cert/SSDP)

    def label(self) -> str:
        if self.webos:
            return "LG webOS TV"
        if self.mac and self.mac[:8] in _LG_OUIS:
            return "LG device"
        if self.ssap_port:
            return f"answers on port {self.ssap_port}"
        return "?"

    def describe(self) -> str:
        left = self.name or self.label()
        bits = [f"{self.ip:<15}", f"{self.mac or 'unknown MAC':<17}", left]
        if self.model:
            bits.append(f"[{self.model}]")
        if self.name:
            bits.append(f"({self.label()})")
        return "  ".join(bits)


def _ssdp_headers(raw: bytes) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in raw.decode("latin-1", "replace").split("\r\n")[1:]:
        key, sep, val = line.partition(":")
        if sep:
            out[key.strip().lower()] = val.strip()
    return out


def _ssdp_search(timeout: float) -> dict[str, dict[str, str]]:
    msg = (
        "M-SEARCH * HTTP/1.1\r\n"
        "HOST: 239.255.255.250:1900\r\n"
        'MAN: "ssdp:discover"\r\n'
        "MX: 2\r\n"
        "ST: ssdp:all\r\n\r\n"
    ).encode()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    sock.settimeout(0.6)
    found: dict[str, dict[str, str]] = {}
    try:
        for _ in range(2):
            try:
                sock.sendto(msg, _SSDP_ADDR)
            except OSError:
                return found
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                data, addr = sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                break
            found.setdefault(addr[0], {}).update(_ssdp_headers(data))
    finally:
        sock.close()
    return found


def _looks_webos(headers: dict[str, str]) -> bool:
    blob = " ".join(headers.values()).lower()
    return any(hint in blob for hint in _WEBOS_HINTS)


def _open_ssap_port(ip: str) -> int | None:
    for port in _SSAP_PORTS:
        if net.tcp_open(ip, port):
            return port
    return None


_HOST_SUFFIXES = (".local", ".lan", ".home", ".home.arpa", ".localdomain")


def _reverse_dns(ip: str, timeout: float = 2.0) -> str:
    """The name the host resolver has for ``ip`` (mDNS/PTR), suffix trimmed."""
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            name = pool.submit(socket.gethostbyaddr, ip).result(timeout=timeout)[0]
    except Exception:  # noqa: BLE001  (herror, timeout, resolver quirks)
        return ""
    name = name.rstrip(".")
    low = name.lower()
    for suffix in _HOST_SUFFIXES:
        if low.endswith(suffix):
            return name[: -len(suffix)]
    return name.split(".")[0]


def _airplay_info(ip: str, timeout: float = 2.5) -> dict:
    """AirPlay /info (2019+ LG TVs): friendly name, model, manufacturer. No pairing."""
    try:
        req = urllib.request.Request(
            f"http://{ip}:7000/info", headers={"User-Agent": "AirPlay/1.0"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            data = plistlib.loads(resp.read())
    except Exception:  # noqa: BLE001  (URLError, timeout, plist errors, ...)
        return {}
    return data if isinstance(data, dict) else {}


def _clean_name(name: str) -> str:
    name = name.strip()
    if name.startswith("[LG] "):
        name = name[5:]
    return name


def _has_lg_cert(ip: str, port: int = 3001, timeout: float = 2.5) -> bool:
    """True if the TLS endpoint presents an 'LG Electronics' certificate."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with socket.create_connection((ip, port), timeout=timeout) as raw:
            with ctx.wrap_socket(raw, server_hostname=ip) as tls:
                der = tls.getpeercert(binary_form=True) or b""
    except (OSError, ssl.SSLError):
        return False
    return b"LG Electronics" in der


def discover(timeout: float = 3.0) -> list[TvCandidate]:
    """Return likely TVs, WebOS-confirmed ones first."""
    candidates: dict[str, TvCandidate] = {}

    for ip, headers in _ssdp_search(min(timeout, 2.5)).items():
        if _looks_webos(headers):
            candidates[ip] = TvCandidate(ip=ip, webos=True)

    others = [ip for ip in net.arp_neighbours() if ip not in candidates]
    if others:
        with ThreadPoolExecutor(max_workers=32) as pool:
            for ip, port in zip(others, pool.map(_open_ssap_port, others)):
                if port is not None:
                    candidates[ip] = TvCandidate(ip=ip, ssap_port=port)

    def _enrich(c: TvCandidate) -> None:
        net.ping(c.ip, 1.0)  # populate the ARP entry
        c.mac = net.neigh_mac(c.ip)
        if c.ssap_port is None:
            c.ssap_port = _open_ssap_port(c.ip)

        info = _airplay_info(c.ip)
        if info:
            c.name = _clean_name(str(info.get("name", "")))
            c.model = str(info.get("model", ""))
            if "lg" in str(info.get("manufacturer", "")).lower() or c.model.startswith(
                ("OLED", "NANO", "QNED", "UHD", "43", "50", "55", "65", "75", "77", "83")
            ):
                c.webos = True

        if not c.name:
            c.name = _reverse_dns(c.ip)
        if not c.webos and c.ssap_port == 3001:
            c.webos = _has_lg_cert(c.ip)

    if candidates:
        with ThreadPoolExecutor(max_workers=16) as pool:
            list(pool.map(_enrich, list(candidates.values())))

    result = [c for c in candidates.values() if c.webos or c.ssap_port]
    result.sort(key=lambda c: (not c.webos, c.ssap_port is None, _ip_key(c.ip)))
    return result


def _ip_key(ip: str) -> tuple[int, ...]:
    try:
        return tuple(int(p) for p in ip.split("."))
    except ValueError:
        return (0,)
