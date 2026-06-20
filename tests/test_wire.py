"""Zero-copy wire codec — byte-faithful to the Go canonical (zap-proto/go).

The keystone is ``test_cross_wire_golden_encode``: this Python Builder must emit
EXACTLY the same 47-byte buffer the Go cross-wire test pins (goldenV1Hex). If it
diverges, the two runtimes no longer share a wire and CI must fail.
"""

import math

import pytest

from zap.wire import (
    MAGIC,
    VERSION1,
    VERSION2,
    BufferTooSmall,
    Builder,
    InvalidMagic,
    InvalidVersion,
    parse,
)

# Shared verbatim with go/zap_crosswire_test.go (goldenV1Hex). The canonical
# object: @0 uint32 0xDEADBEEF, @8 text "zap", @16 bytes 01020304, dataSize 24.
GOLDEN_V1_HEX = (
    "5a41500001000000100000002f000000efbeadde0000000010000000030000000b000000040000007a617001020304"
)


def build_canonical() -> bytes:
    b = Builder(64)
    ob = b.start_object(24)
    ob.set_uint32(0, 0xDEADBEEF)
    ob.set_text(8, "zap")
    ob.set_bytes(16, b"\x01\x02\x03\x04")
    ob.finish_as_root()
    return b.finish()


def test_cross_wire_golden_encode():
    """This Builder emits the exact shared golden vector (byte-for-byte)."""
    assert build_canonical().hex() == GOLDEN_V1_HEX


def test_cross_wire_golden_decode():
    """This reader decodes every field of the golden buffer."""
    msg = parse(bytes.fromhex(GOLDEN_V1_HEX))
    assert msg.version == VERSION1
    assert msg.size == 47
    root = msg.root()
    assert root.uint32(0) == 0xDEADBEEF
    assert root.text(8) == "zap"
    assert root.bytes(16) == b"\x01\x02\x03\x04"


def test_accepts_v2_header():
    """A v2-tagged copy of the golden buffer parses (forward-compatible read)."""
    buf = bytearray(bytes.fromhex(GOLDEN_V1_HEX))
    buf[4:6] = (VERSION2).to_bytes(2, "little")
    msg = parse(bytes(buf))
    assert msg.version == VERSION2
    assert msg.root().uint32(0) == 0xDEADBEEF


def test_rejects_bad_magic():
    buf = bytearray(bytes.fromhex(GOLDEN_V1_HEX))
    buf[0] = ord("X")
    with pytest.raises(InvalidMagic):
        parse(bytes(buf))


def test_rejects_bad_version():
    buf = bytearray(bytes.fromhex(GOLDEN_V1_HEX))
    buf[4:6] = (3).to_bytes(2, "little")
    with pytest.raises(InvalidVersion):
        parse(bytes(buf))


def test_rejects_short_buffer():
    with pytest.raises(BufferTooSmall):
        parse(b"ZAP\x00\x01\x00")


def test_rejects_size_below_header():
    buf = bytearray(bytes.fromhex(GOLDEN_V1_HEX))
    buf[12:16] = (0).to_bytes(4, "little")
    with pytest.raises(BufferTooSmall):
        parse(bytes(buf))


def test_rejects_size_past_buffer():
    buf = bytearray(bytes.fromhex(GOLDEN_V1_HEX))
    buf[12:16] = (10_000).to_bytes(4, "little")
    with pytest.raises(BufferTooSmall):
        parse(bytes(buf))


def test_all_scalar_roundtrip():
    b = Builder()
    ob = b.start_object(64)
    ob.set_bool(0, True)
    ob.set_uint8(1, 200)
    ob.set_int8(2, -5)
    ob.set_uint16(4, 60000)
    ob.set_int16(6, -1234)
    ob.set_uint32(8, 0xCAFEBABE)
    ob.set_int32(12, -123456)
    ob.set_uint64(16, 0x1122334455667788)
    ob.set_int64(24, -9_000_000_000)
    ob.set_float32(32, 1.5)
    ob.set_float64(40, math.pi)
    ob.finish_as_root()
    root = parse(b.finish()).root()
    assert root.bool(0) is True
    assert root.uint8(1) == 200
    assert root.int8(2) == -5
    assert root.uint16(4) == 60000
    assert root.int16(6) == -1234
    assert root.uint32(8) == 0xCAFEBABE
    assert root.int32(12) == -123456
    assert root.uint64(16) == 0x1122334455667788
    assert root.int64(24) == -9_000_000_000
    assert root.float32(32) == 1.5
    assert root.float64(40) == math.pi


def test_text_bytes_empty_and_unicode():
    b = Builder()
    ob = b.start_object(24)
    ob.set_text(0, "héllo ✓")
    ob.set_bytes(8, b"")  # null pointer
    ob.set_bytes_fixed(16, b"\xde\xad\xbe\xef")
    ob.finish_as_root()
    root = parse(b.finish()).root()
    assert root.text(0) == "héllo ✓"
    assert root.bytes(8) == b""
    assert root.bytes_fixed(16, 4) == b"\xde\xad\xbe\xef"


def test_flat_uint_list():
    b = Builder()
    lb = b.start_list(4)
    for v in (10, 20, 30, 40):
        lb.add_uint32(v)
    list_off, length = lb.finish()
    ob = b.start_object(8)
    ob.set_list(0, list_off, length)
    ob.finish_as_root()
    lst = parse(b.finish()).root().list(0)
    assert len(lst) == 4
    assert [lst.uint32(i) for i in range(4)] == [10, 20, 30, 40]


def test_variable_element_list_object():
    # Build three inner objects, embed each as a variable-length list entry.
    inners = []
    for x in (0xAAAA0001, 0xAAAA0002, 0xAAAA0003):
        ib = Builder()
        iob = ib.start_object(4)
        iob.set_uint32(0, x)
        iob.finish_as_root()
        inners.append(ib.finish())

    b = Builder()
    lb = b.start_list(0)
    for buf in inners:
        lb.add_object_bytes(buf)
    list_off, length = lb.finish()
    ob = b.start_object(8)
    ob.set_list(0, list_off, length)
    ob.finish_as_root()

    lst = parse(b.finish()).root().list(0)
    assert len(lst) == 3
    assert [lst.object_at(i).uint32(0) for i in range(3)] == [0xAAAA0001, 0xAAAA0002, 0xAAAA0003]

    # The single-pass cursor yields the same elements.
    seen = []
    lst.each(lambda i, o: seen.append(o.uint32(0)) or True)
    assert seen == [0xAAAA0001, 0xAAAA0002, 0xAAAA0003]


def test_variable_element_list_bytes():
    payloads = [b"alpha", b"", b"gamma-\xff\x00"]
    b = Builder()
    lb = b.start_list(0)
    for p in payloads:
        lb.add_object_bytes(p)
    list_off, length = lb.finish()
    ob = b.start_object(8)
    ob.set_list(0, list_off, length)
    ob.finish_as_root()
    lst = parse(b.finish()).root().list(0)
    assert [lst.bytes_at(i) for i in range(3)] == payloads
    seen: list[bytes] = []
    lst.each_bytes(lambda i, p: seen.append(p) or True)
    assert seen == payloads


def test_nested_object_roundtrip():
    b = Builder()
    inner = b.start_object(8)
    inner.set_uint32(0, 0x12345678)
    inner.set_uint32(4, 0x9ABCDEF0)
    inner_off = inner.finish()
    outer = b.start_object(8)
    outer.set_uint32(0, 1)
    outer.set_object(4, inner_off)
    outer.finish_as_root()
    root = parse(b.finish()).root()
    assert root.uint32(0) == 1
    sub = root.object(4)
    assert not sub.is_null()
    assert sub.uint32(0) == 0x12345678
    assert sub.uint32(4) == 0x9ABCDEF0


def test_reader_rejects_backward_pointer_into_header():
    """A crafted backward object/list pointer aliasing the header is rejected.

    Pins the 'both readers agree on accept/reject for every input' invariant —
    Go's Object()/List() floor absOffset at HEADER_SIZE; so must this reader.
    """
    # Root object at offset 16 with one pointer field @0 holding relOffset -8,
    # which would resolve to absolute offset 8 (inside the header).
    buf = bytearray(48)
    buf[0:4] = MAGIC
    buf[4:6] = (VERSION1).to_bytes(2, "little")
    buf[8:12] = (16).to_bytes(4, "little")  # root offset
    buf[12:16] = (48).to_bytes(4, "little")  # size
    # pointer field @ root+0 (= byte 16): signed relOffset -8 -> abs 8
    buf[16:20] = (-8 & 0xFFFFFFFF).to_bytes(4, "little")
    buf[20:24] = (1).to_bytes(4, "little")  # list length word (harmless)
    root = parse(bytes(buf)).root()
    assert root.object(0).is_null()  # rejected, not offset-8 alias
    assert root.list(0).is_null()  # rejected


def test_list_length_clamped():
    """A forged 0xFFFFFFFF list length is rejected (no 4G-iteration DoS)."""
    buf = bytearray(48)
    buf[0:4] = MAGIC
    buf[4:6] = (VERSION1).to_bytes(2, "little")
    buf[8:12] = (16).to_bytes(4, "little")
    buf[12:16] = (48).to_bytes(4, "little")
    buf[16:20] = (8).to_bytes(4, "little")  # forward relOffset 8 -> abs 24 (valid)
    buf[20:24] = (0xFFFFFFFF).to_bytes(4, "little")  # forged length
    lst = parse(bytes(buf)).root().list(0)
    assert lst.is_null()
