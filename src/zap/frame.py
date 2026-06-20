"""ZAP router envelope — the canonical Python codec.

Byte-for-byte compatible with ``zap-proto/zapd``'s ``src/frame.rs``. This is the
ONE Python implementation of the wire; everything (hanzo-mcp, the native host,
tools) imports it from here — no second copies.

Envelope (little-endian):
    u32 len            bytes that follow
    u8  type
    u16 flags
    u16 from_len
    u16 to_len
    u32 payload_len
    bytes from         source id (zapd stamps the verified id)
    bytes to           destination (empty -> the frame is for zapd)
    bytes payload      opaque

Routing: ``to`` empty -> for zapd (hello / providers.list); ``to`` set ->
forwarded opaquely. The payload is never parsed by the router.
"""

from __future__ import annotations

import os
import socket
import struct
from dataclasses import dataclass, field

# Envelope types (match frame.rs).
HELLO = 1
WELCOME = 2
PROVIDERS_LIST = 3
PROVIDERS = 4
PEER_CONNECTED = 5
PEER_DISCONNECTED = 6
ERROR = 7
ROUTE = 16
RESPONSE = 17
EVENT = 18

# Roles.
ROLE_PROVIDER = 1
ROLE_CONSUMER = 2
ROLE_ROUTER = 3

_HEADER = struct.Struct("<BHHHI")  # type, flags, from_len, to_len, payload_len

# from_len / to_len are u16 on the wire (canonical zapd/src/frame.rs) — node ids
# are short identifiers by construction. An id that overflows u16 is a caller
# error; reject it cleanly instead of letting struct.pack raise a raw error.
_MAX_ID = 0xFFFF
_MAX_FRAME = 64 * 1024 * 1024  # mirrors zapd MAX_FRAME


def socket_path() -> str:
    """Resolve the brand-neutral zapd socket: $ZAP_SOCK ->
    $XDG_RUNTIME_DIR/zap/zapd.sock -> ~/.zap/run/zapd.sock."""
    p = os.environ.get("ZAP_SOCK")
    if p:
        return p
    xrd = os.environ.get("XDG_RUNTIME_DIR")
    if xrd:
        return os.path.join(xrd, "zap", "zapd.sock")
    return os.path.expanduser("~/.zap/run/zapd.sock")


@dataclass
class Frame:
    typ: int
    frm: str = ""
    to: str = ""
    payload: bytes = b""
    flags: int = 0

    def encode(self) -> bytes:
        fb, tb = self.frm.encode(), self.to.encode()
        if len(fb) > _MAX_ID or len(tb) > _MAX_ID:
            raise ValueError(
                f"zap: routing id too long (from={len(fb)} to={len(tb)}, max {_MAX_ID})"
            )
        body = (
            _HEADER.pack(self.typ, self.flags, len(fb), len(tb), len(self.payload))
            + fb
            + tb
            + self.payload
        )
        return struct.pack("<I", len(body)) + body

    @classmethod
    def read(cls, sock: socket.socket) -> Frame:
        (length,) = struct.unpack("<I", _recvn(sock, 4))
        if length < _HEADER.size or length > _MAX_FRAME:
            raise ValueError(f"zap: frame length {length} out of range")
        buf = _recvn(sock, length)
        typ, flags, fl, tl, pl = _HEADER.unpack_from(buf, 0)
        o = _HEADER.size
        # Routing ids are forwarded opaquely; a peer may stamp non-UTF-8 bytes.
        # Decode leniently so a malformed id cannot crash the consumer.
        frm = buf[o : o + fl].decode("utf-8", "replace")
        o += fl
        to = buf[o : o + tl].decode("utf-8", "replace")
        o += tl
        return cls(typ=typ, frm=frm, to=to, payload=buf[o : o + pl], flags=flags)


def _recvn(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        c = sock.recv(n - len(buf))
        if not c:
            raise EOFError("zapd connection closed")
        buf += c
    return buf


# ── Control-message bodies (the router's own protocol) ─────────────────────
def _put_str(s: str) -> bytes:
    b = s.encode()
    return struct.pack("<H", len(b)) + b


def encode_hello(role: int, brand: str, caps: list[str]) -> bytes:
    """HELLO body: role(u8) + brand(str) + caps(u16 count + str...)."""
    b = bytes([role]) + _put_str(brand) + struct.pack("<H", len(caps))
    for c in caps:
        b += _put_str(c)
    return b


@dataclass
class Provider:
    id: str
    role: int
    brand: str
    caps: list[str] = field(default_factory=list)


def parse_providers(pay: bytes) -> list[Provider]:
    (n,) = struct.unpack_from("<H", pay, 0)
    o = 2
    out = []
    for _ in range(n):
        (idl,) = struct.unpack_from("<H", pay, o)
        o += 2
        pid = pay[o : o + idl].decode()
        o += idl
        role = pay[o]
        o += 1
        (bl,) = struct.unpack_from("<H", pay, o)
        o += 2
        brand = pay[o : o + bl].decode()
        o += bl
        (cn,) = struct.unpack_from("<H", pay, o)
        o += 2
        caps = []
        for _ in range(cn):
            (cl,) = struct.unpack_from("<H", pay, o)
            o += 2
            caps.append(pay[o : o + cl].decode())
            o += cl
        out.append(Provider(id=pid, role=role, brand=brand, caps=caps))
    return out


# ── Optional opaque command payload codec (end-to-end; router never sees it) ─
# This codec is consumed only by ZAP Python peers (the router forwards the
# payload opaquely), so it carries a 1-byte value type tag — 0=bytes, 1=str —
# letting decode_cmd return exactly what encode_cmd was given. A value that
# came in as str comes back as str; bytes come back as bytes.
_VAL_BYTES = 0
_VAL_STR = 1


def encode_cmd(method: str, params: dict[str, str | bytes]) -> bytes:
    """method(str) + params(u16 count of key:str -> tag:u8 + value:bytes)."""
    b = _put_str(method) + struct.pack("<H", len(params))
    for k, v in params.items():
        if isinstance(v, str):
            tag, vb = _VAL_STR, v.encode()
        else:
            tag, vb = _VAL_BYTES, bytes(v)
        b += _put_str(k) + bytes([tag]) + struct.pack("<I", len(vb)) + vb
    return b


def decode_cmd(pay: bytes) -> tuple[str, dict[str, str | bytes]]:
    o = 0
    (ml,) = struct.unpack_from("<H", pay, o)
    o += 2
    method = pay[o : o + ml].decode()
    o += ml
    (n,) = struct.unpack_from("<H", pay, o)
    o += 2
    params: dict[str, str | bytes] = {}
    for _ in range(n):
        (kl,) = struct.unpack_from("<H", pay, o)
        o += 2
        k = pay[o : o + kl].decode()
        o += kl
        tag = pay[o]
        o += 1
        (vl,) = struct.unpack_from("<I", pay, o)
        o += 4
        raw = pay[o : o + vl]
        o += vl
        params[k] = raw.decode() if tag == _VAL_STR else raw
    return method, params
