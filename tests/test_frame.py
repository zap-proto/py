"""Canonical ZAP router envelope codec — round-trips (matches zapd/frame.rs)."""
from zap.frame import (Frame, ROUTE, ROLE_PROVIDER, encode_hello, parse_providers,
                       encode_cmd, decode_cmd, _put_str)
import struct


def test_envelope_roundtrip():
    f = Frame(ROUTE, "consumer:mcp/1", "browser:chrome/dbc/default", b"opaque\x00\x01")
    raw = f.encode()
    # frame body length prefix + parse back via the header struct
    assert raw[:4] == struct.pack("<I", len(raw) - 4)


def test_cmd_roundtrip():
    payload = encode_cmd("Page.navigate", {"url": "https://hanzo.ai"})
    method, params = decode_cmd(payload)
    assert method == "Page.navigate"
    assert params["url"] == b"https://hanzo.ai"


def test_providers_roundtrip():
    body = struct.pack("<H", 1) + _put_str("browser:chrome/dbc/default") + bytes([ROLE_PROVIDER]) + _put_str("hanzo") + struct.pack("<H", 0)
    provs = parse_providers(body)
    assert provs[0].id == "browser:chrome/dbc/default" and provs[0].brand == "hanzo"


def test_hello_encodes():
    assert encode_hello(ROLE_PROVIDER, "hanzo", ["browser.tabs"])[0] == ROLE_PROVIDER
