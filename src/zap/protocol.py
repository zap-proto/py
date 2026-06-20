"""ZAP wire-format protocol — binary framing for Hanzo browser/agent ↔ server.

Pure-stdlib codec for the canonical 9-byte header + JSON payload frame used
by hanzo-mcp's ZapServer and the Hanzo browser extension. Mirrors the
TypeScript reference at
``hanzoai/extension/packages/browser/src/shared/zap.ts``.

Wire layout::

    [ 0x5A 0x41 0x50 0x01 ][ type:1 ][ length:4 BE ][ JSON payload ]

This module has no third-party deps so it works on a minimal install — the
zap-based parts of the ``zap`` package may be imported lazily.
"""

from __future__ import annotations

import json
import struct
from typing import Any

# ── Protocol constants ────────────────────────────────────────────────────

ZAP_MAGIC: bytes = b"\x5a\x41\x50\x01"
HEADER_SIZE: int = 9  # 4 magic + 1 type + 4 length

MSG_HANDSHAKE: int = 0x01
MSG_HANDSHAKE_OK: int = 0x02
MSG_REQUEST: int = 0x10
MSG_RESPONSE: int = 0x11
MSG_PING: int = 0xFE
MSG_PONG: int = 0xFF

MAX_MESSAGE_SIZE: int = 16 * 1024 * 1024  # 16 MiB

# Server-side bind candidates. Discovery from the client side is mDNS-only
# per HIP-0069 (``_hanzo._tcp.local.``) — the port list is retained only for
# server bind fallback when no preferred port is provided.
ZAP_PORTS: tuple[int, ...] = (9999, 9998, 9997, 9996, 9995)

__all__ = [
    "ZAP_MAGIC",
    "HEADER_SIZE",
    "MAX_MESSAGE_SIZE",
    "MSG_HANDSHAKE",
    "MSG_HANDSHAKE_OK",
    "MSG_REQUEST",
    "MSG_RESPONSE",
    "MSG_PING",
    "MSG_PONG",
    "ZAP_PORTS",
    "encode",
    "decode",
    "decode_stream",
]


# ── Codec ─────────────────────────────────────────────────────────────────


def encode(msg_type: int, payload: Any) -> bytes:
    """Encode a payload as a ZAP frame: magic + type + length + JSON."""
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(body) > MAX_MESSAGE_SIZE:
        raise ValueError(f"ZAP payload exceeds MAX_MESSAGE_SIZE ({len(body)} > {MAX_MESSAGE_SIZE})")
    return ZAP_MAGIC + struct.pack("!BL", msg_type & 0xFF, len(body)) + body


def decode(frame: bytes) -> tuple[int, Any] | None:
    """Decode a single ZAP frame. Returns ``(msg_type, payload)`` or ``None``.

    Returns ``None`` for malformed frames (bad magic, short buffer, oversize,
    or invalid JSON). Trailing bytes after the first frame are ignored — to
    demux a byte stream of back-to-back frames use :func:`decode_stream`.
    """
    result = decode_stream(frame)
    if result is None:
        return None
    msg_type, payload, _consumed = result
    return msg_type, payload


def decode_stream(buf: bytes) -> tuple[int, Any, int] | None:
    """Decode the first ZAP frame in ``buf``; report bytes consumed.

    Returns ``(msg_type, payload, consumed)`` where ``consumed`` is the total
    frame length (header + payload) — advance the read cursor by it, then call
    again for the next frame. Returns ``None`` when ``buf`` does not yet hold a
    complete, well-formed frame (need more bytes, bad magic, oversize, or
    invalid JSON), so a stream consumer can wait for more data.
    """
    if len(buf) < HEADER_SIZE or buf[:4] != ZAP_MAGIC:
        return None
    msg_type = buf[4]
    (length,) = struct.unpack("!L", buf[5:9])
    if length > MAX_MESSAGE_SIZE:
        return None
    end = HEADER_SIZE + length
    if len(buf) < end:
        return None
    try:
        payload = json.loads(buf[HEADER_SIZE:end].decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return msg_type, payload, end
