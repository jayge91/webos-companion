from __future__ import annotations


def encode_pnp(pnp: str) -> bytes:
    a, b, c = (ord(ch) - ord("A") + 1 for ch in pnp.upper())
    packed = (a << 10) | (b << 5) | c
    return bytes([(packed >> 8) & 0xFF, packed & 0xFF])


def make_edid(pnp: str = "GSM") -> bytes:
    edid = bytearray(128)
    edid[0:8] = bytes.fromhex("00ffffffffffff00")
    edid[8:10] = encode_pnp(pnp)
    edid[127] = (-sum(edid[:127])) & 0xFF  # valid checksum byte
    return bytes(edid)
