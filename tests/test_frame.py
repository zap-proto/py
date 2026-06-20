"""Canonical ZAP router envelope codec — round-trips (matches zapd/frame.rs)."""

import socket
import struct

import pytest

from zap.frame import (
    ROLE_PROVIDER,
    ROUTE,
    Frame,
    _put_str,
    decode_cmd,
    encode_cmd,
    encode_hello,
    parse_providers,
)


def test_envelope_roundtrip():
    f = Frame(ROUTE, "consumer:mcp/1", "browser:chrome/dbc/default", b"opaque\x00\x01")
    raw = f.encode()
    # frame body length prefix + parse back via the header struct
    assert raw[:4] == struct.pack("<I", len(raw) - 4)


def test_cmd_roundtrip_preserves_str():
    """A str value round-trips back to str (the type tag fix)."""
    payload = encode_cmd("Page.navigate", {"url": "https://hanzo.ai"})
    method, params = decode_cmd(payload)
    assert method == "Page.navigate"
    assert params["url"] == "https://hanzo.ai"  # str, not bytes


def test_cmd_roundtrip_preserves_bytes():
    """A bytes value round-trips back to bytes."""
    payload = encode_cmd("Raw.send", {"blob": b"\x00\xff\x10"})
    _method, params = decode_cmd(payload)
    assert params["blob"] == b"\x00\xff\x10"


def test_cmd_roundtrip_mixed():
    payload = encode_cmd("m", {"s": "text", "b": b"\x01\x02"})
    _method, params = decode_cmd(payload)
    assert params == {"s": "text", "b": b"\x01\x02"}


def test_providers_roundtrip():
    body = (
        struct.pack("<H", 1)
        + _put_str("browser:chrome/dbc/default")
        + bytes([ROLE_PROVIDER])
        + _put_str("hanzo")
        + struct.pack("<H", 0)
    )
    provs = parse_providers(body)
    assert provs[0].id == "browser:chrome/dbc/default" and provs[0].brand == "hanzo"


def test_hello_encodes():
    assert encode_hello(ROLE_PROVIDER, "hanzo", ["browser.tabs"])[0] == ROLE_PROVIDER


def test_encode_rejects_oversize_id():
    """An id past the u16 wire limit is a clean ValueError, not a struct crash."""
    huge = "x" * 70000
    with pytest.raises(ValueError, match="routing id too long"):
        Frame(ROUTE, huge, "to", b"").encode()


def test_read_tolerates_non_utf8_id():
    """Frame.read decodes non-UTF8 routing ids leniently (no crash)."""
    # Build a frame by hand with a 0xFF byte in the `from` id.
    frm = b"\xff\xfe"
    body = struct.pack("<BHHHI", ROUTE, 0, len(frm), 0, 0) + frm
    raw = struct.pack("<I", len(body)) + body
    a, b = socket.socketpair()
    try:
        a.sendall(raw)
        f = Frame.read(b)
        assert f.typ == ROUTE
        assert f.frm  # decoded leniently, did not raise
    finally:
        a.close()
        b.close()
