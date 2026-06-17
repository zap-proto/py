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
        body = _HEADER.pack(self.typ, self.flags, len(fb), len(tb), len(self.payload)) + fb + tb + self.payload
        return struct.pack("<I", len(body)) + body

    @classmethod
    def read(cls, sock: socket.socket) -> "Frame":
        (length,) = struct.unpack("<I", _recvn(sock, 4))
        buf = _recvn(sock, length)
        typ, flags, fl, tl, pl = _HEADER.unpack_from(buf, 0)
        o = _HEADER.size
        frm = buf[o : o + fl].decode(); o += fl
        to = buf[o : o + tl].decode(); o += tl
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


def encode_hello(role: int, brand: str, caps) -> bytes:
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
    caps: list = field(default_factory=list)


def parse_providers(pay: bytes) -> list:
    (n,) = struct.unpack_from("<H", pay, 0)
    o = 2
    out = []
    for _ in range(n):
        (idl,) = struct.unpack_from("<H", pay, o); o += 2
        pid = pay[o : o + idl].decode(); o += idl
        role = pay[o]; o += 1
        (bl,) = struct.unpack_from("<H", pay, o); o += 2
        brand = pay[o : o + bl].decode(); o += bl
        (cn,) = struct.unpack_from("<H", pay, o); o += 2
        caps = []
        for _ in range(cn):
            (cl,) = struct.unpack_from("<H", pay, o); o += 2
            caps.append(pay[o : o + cl].decode()); o += cl
        out.append(Provider(id=pid, role=role, brand=brand, caps=caps))
    return out


# ── Optional opaque command payload codec (end-to-end; router never sees it) ─
def encode_cmd(method: str, params: dict) -> bytes:
    """method(str) + params(u16 count of key:str -> value:bytes)."""
    b = _put_str(method) + struct.pack("<H", len(params))
    for k, v in params.items():
        vb = v.encode() if isinstance(v, str) else bytes(v)
        b += _put_str(k) + struct.pack("<I", len(vb)) + vb
    return b


def decode_cmd(pay: bytes):
    o = 0
    (ml,) = struct.unpack_from("<H", pay, o); o += 2
    method = pay[o : o + ml].decode(); o += ml
    (n,) = struct.unpack_from("<H", pay, o); o += 2
    params = {}
    for _ in range(n):
        (kl,) = struct.unpack_from("<H", pay, o); o += 2
        k = pay[o : o + kl].decode(); o += kl
        (vl,) = struct.unpack_from("<I", pay, o); o += 4
        params[k] = pay[o : o + vl]; o += vl
    return method, params
