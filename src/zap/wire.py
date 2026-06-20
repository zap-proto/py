"""ZAP wire format — the zero-copy codec.

Pure-stdlib Python port of the canonical Go runtime (``zap-proto/go``:
``zap.go`` + ``builder.go`` + ``accessors.go`` + ``list_cursor.go``). Byte-for-byte
compatible: this module reads what Go writes and writes what Go reads, pinned by
the shared cross-wire golden vector (see ``tests/test_wire.py``).

Wire layout::

    +-----------------------------------------------+
    | Header (16 bytes)                             |
    |   Magic   (4): b"ZAP\\x00"                     |
    |   Version (2): 1 or 2                          |
    |   Flags   (2): compression / encryption / ... |
    |   Root    (4): offset to the root object      |
    |   Size    (4): total message size             |
    +-----------------------------------------------+
    | Data segment (variable): structs, lists, text |
    +-----------------------------------------------+

All multi-byte integers are little-endian. Field offsets within an object are
fixed by the schema; out-of-line text/bytes/list payloads are reached through a
relative offset stored at the field position.

The reader ACCEPTS both Version1 and Version2 headers (forward-compatible parse);
the two differ only in the meaning of struct byte 0. Callers that require a
specific schema generation gate on :meth:`Message.version` after :func:`parse`.

This module has ZERO third-party dependencies — it is always importable.
"""

from __future__ import annotations

import struct
from collections.abc import Callable

# Builtins shadowed by spec-named accessors (Object.bytes, List.object, ...).
# Alias the builtin so annotations inside those classes still resolve to it.
_bytes = bytes

#: Anything the struct codecs accept as a read buffer.
_Buf = bytes | bytearray | memoryview

# ── Wire constants (identical to the Go canonical) ─────────────────────────

HEADER_SIZE = 16
MAGIC = b"ZAP\x00"

VERSION1 = 1
VERSION2 = 2
#: Version this runtime's Builder emits by default. The pure-stdlib baseline
#: emits Version1, matching ``zap-proto/go``; both readers accept both.
VERSION = VERSION1

#: Canonical TCP port for ZAP transport (80 -> HTTP, 9999 -> ZAP).
DEFAULT_PORT = 9999

#: Data segments are 8-byte aligned.
ALIGNMENT = 8

# Header flags.
FLAG_NONE = 0
FLAG_COMPRESSED = 1 << 0
FLAG_ENCRYPTED = 1 << 1
FLAG_SIGNED = 1 << 2

# Pre-compiled little-endian codecs (faster + clearer than ad-hoc shifts).
_U16 = struct.Struct("<H")
_U32 = struct.Struct("<I")
_U64 = struct.Struct("<Q")
_I32 = struct.Struct("<i")
_F32 = struct.Struct("<f")
_F64 = struct.Struct("<d")


class ZapError(ValueError):
    """A ZAP wire-format error (invalid magic, version, or bounds)."""


class InvalidMagic(ZapError):
    """The buffer does not begin with the ZAP magic."""


class InvalidVersion(ZapError):
    """The header version is not one this runtime accepts."""


class BufferTooSmall(ZapError):
    """The buffer is shorter than its declared size or the header."""


def _u32(data: _Buf, pos: int) -> int:
    return int(_U32.unpack_from(data, pos)[0])


# ── Reader ─────────────────────────────────────────────────────────────────


def parse(data: bytes) -> Message:
    """Parse a ZAP message from ``data`` without copying.

    Accepts Version1 and Version2 headers. Raises :class:`InvalidMagic`,
    :class:`InvalidVersion`, or :class:`BufferTooSmall` on a malformed buffer.

    The declared size must be at least :data:`HEADER_SIZE` (a size=0 buffer
    would otherwise pass and then fail on a subsequent root/flags read) and at
    most ``len(data)``.
    """
    if len(data) < HEADER_SIZE:
        raise BufferTooSmall("zap: buffer too small")
    if bytes(data[0:4]) != MAGIC:
        raise InvalidMagic("zap: invalid magic bytes")
    version = _U16.unpack_from(data, 4)[0]
    if version != VERSION1 and version != VERSION2:
        raise InvalidVersion("zap: unsupported version")
    size = _u32(data, 12)
    if size < HEADER_SIZE or size > len(data):
        raise BufferTooSmall("zap: buffer too small")
    return Message(memoryview(data)[:size])


class Message:
    """A parsed ZAP message that can be read zero-copy.

    Construct via :func:`parse`. The underlying buffer is held as a
    :class:`memoryview`; accessor results that return ``bytes``/``str`` slice
    it without copying the payload.
    """

    __slots__ = ("_data",)

    def __init__(self, data: memoryview):
        self._data = data

    @property
    def data(self) -> memoryview:
        """The underlying buffer (truncated to the declared size)."""
        return self._data

    @property
    def version(self) -> int:
        """The wire version (:data:`VERSION1` or :data:`VERSION2`)."""
        return int(_U16.unpack_from(self._data, 4)[0])

    @property
    def flags(self) -> int:
        """The header flags."""
        return int(_U16.unpack_from(self._data, 6)[0])

    @property
    def size(self) -> int:
        """The total message size in bytes."""
        return len(self._data)

    def root(self) -> Object:
        """The root object of the message."""
        return Object(self._data, _u32(self._data, 8))


class Object:
    """A zero-copy view into a ZAP struct.

    Field accessors take the schema-fixed byte offset of the field within the
    object's fixed section. Out-of-bounds reads return the zero value (0 /
    ``b""`` / ``None``) rather than raising, matching the Go runtime so both
    readers agree on every input.
    """

    __slots__ = ("_data", "_offset")

    def __init__(self, data: memoryview, offset: int):
        self._data = data
        self._offset = offset

    def is_null(self) -> bool:
        """True if this is the null object (offset 0)."""
        return self._offset == 0

    # Unsigned integers.
    def uint8(self, field_offset: int) -> int:
        pos = self._offset + field_offset
        if pos >= len(self._data):
            return 0
        return int(self._data[pos])

    def uint16(self, field_offset: int) -> int:
        pos = self._offset + field_offset
        if pos + 2 > len(self._data):
            return 0
        return int(_U16.unpack_from(self._data, pos)[0])

    def uint32(self, field_offset: int) -> int:
        pos = self._offset + field_offset
        if pos + 4 > len(self._data):
            return 0
        return int(_U32.unpack_from(self._data, pos)[0])

    def uint64(self, field_offset: int) -> int:
        pos = self._offset + field_offset
        if pos + 8 > len(self._data):
            return 0
        return int(_U64.unpack_from(self._data, pos)[0])

    # Signed integers (two's-complement of the unsigned read).
    def int8(self, field_offset: int) -> int:
        v = self.uint8(field_offset)
        return v - 256 if v >= 128 else v

    def int16(self, field_offset: int) -> int:
        v = self.uint16(field_offset)
        return v - 65536 if v >= 32768 else v

    def int32(self, field_offset: int) -> int:
        v = self.uint32(field_offset)
        return v - 4294967296 if v >= 2147483648 else v

    def int64(self, field_offset: int) -> int:
        v = self.uint64(field_offset)
        return v - 18446744073709551616 if v >= 9223372036854775808 else v

    # Floats / bool.
    def float32(self, field_offset: int) -> float:
        pos = self._offset + field_offset
        if pos + 4 > len(self._data):
            return 0.0
        return float(_F32.unpack_from(self._data, pos)[0])

    def float64(self, field_offset: int) -> float:
        pos = self._offset + field_offset
        if pos + 8 > len(self._data):
            return 0.0
        return float(_F64.unpack_from(self._data, pos)[0])

    def bool(self, field_offset: int) -> bool:
        return self.uint8(field_offset) != 0

    def text(self, field_offset: int) -> str:
        """Read a UTF-8 string at ``field_offset`` (decoded from the slice)."""
        b = self.bytes(field_offset)
        if not b:
            return ""
        return _bytes(b).decode("utf-8", "surrogatepass")

    def bytes(self, field_offset: int) -> _bytes:
        """Read an out-of-line bytes payload at ``field_offset``.

        The field holds an unsigned forward relative offset (4 bytes) followed
        by a length (4 bytes). A null pointer (relOffset 0) yields ``b""``. The
        target may not land inside the wire header — any absolute position
        below :data:`HEADER_SIZE` is rejected (returns ``b""``), closing the
        pointer-escape surface.
        """
        pos = self._offset + field_offset
        if pos + 4 > len(self._data):
            return b""
        rel = _u32(self._data, pos)
        if rel == 0:
            return b""
        len_pos = pos + 4
        if len_pos + 4 > len(self._data):
            return b""
        length = _u32(self._data, len_pos)
        abs_pos = pos + rel
        if abs_pos < HEADER_SIZE:
            return b""
        if abs_pos + length > len(self._data):
            return b""
        return _bytes(self._data[abs_pos : abs_pos + length])

    def bytes_fixed(self, field_offset: int, n: int) -> _bytes:
        """Read ``n`` inline bytes at ``field_offset`` (``bytes_fixed[N]``)."""
        if n <= 0:
            return b""
        pos = self._offset + field_offset
        if pos < 0 or pos + n > len(self._data):
            return b""
        return _bytes(self._data[pos : pos + n])

    def object(self, field_offset: int) -> Object:
        """Read a nested object at ``field_offset``.

        The field holds a *signed* relative offset: a builder may finalize a
        nested object before its parent, in which case the pointer is negative.
        Any absolute offset below :data:`HEADER_SIZE` (aliasing the header) or
        past the buffer is rejected, returning the null object.
        """
        pos = self._offset + field_offset
        if pos + 4 > len(self._data):
            return Object(self._data, 0)
        rel = int(_I32.unpack_from(self._data, pos)[0])
        if rel == 0:
            return Object(self._data, 0)
        abs_offset = pos + rel
        if abs_offset < HEADER_SIZE or abs_offset >= len(self._data):
            return Object(self._data, 0)
        return Object(self._data, abs_offset)

    def list(self, field_offset: int) -> List:
        """Read a list at ``field_offset``.

        The field holds a *signed* relative offset (4 bytes) followed by an
        element count (4 bytes). The count is clamped to the message size — an
        attacker-set ``0xFFFFFFFF`` would otherwise drive a ``for i in
        range(len)`` loop 4G times. Any absolute offset below
        :data:`HEADER_SIZE` is rejected.
        """
        pos = self._offset + field_offset
        if pos + 8 > len(self._data):
            return List(None, 0, 0)
        rel = int(_I32.unpack_from(self._data, pos)[0])
        if rel == 0:
            return List(None, 0, 0)
        length = _u32(self._data, pos + 4)
        if length > len(self._data):
            return List(None, 0, 0)
        abs_offset = pos + rel
        if abs_offset < HEADER_SIZE or abs_offset >= len(self._data):
            return List(None, 0, 0)
        return List(self._data, abs_offset, length)


class List:
    """A zero-copy view into a ZAP list.

    Two physical shapes share this view, distinguished by accessor:

    * **flat lists** — fixed-stride scalar elements (:meth:`uint8`,
      :meth:`uint32`, :meth:`uint64`, :meth:`object`);
    * **variable-element lists** — a stream of ``[u32 length][payload]`` entries
      (:meth:`object_at`, :meth:`bytes_at`, :meth:`each_bytes`, :meth:`each`),
      the shape :meth:`ListBuilder.add_object_bytes` emits.
    """

    __slots__ = ("_data", "_offset", "_length")

    def __init__(self, data: memoryview | None, offset: int, length: int):
        self._data = data
        self._offset = offset
        self._length = length

    def __len__(self) -> int:
        return self._length

    def is_null(self) -> bool:
        return self._data is None

    # ── Flat fixed-stride accessors ────────────────────────────────────────
    def uint8(self, i: int) -> int:
        if self._data is None or i < 0 or i >= self._length:
            return 0
        pos = self._offset + i
        if pos >= len(self._data):
            return 0
        return int(self._data[pos])

    def uint32(self, i: int) -> int:
        if self._data is None or i < 0 or i >= self._length:
            return 0
        pos = self._offset + i * 4
        if pos + 4 > len(self._data):
            return 0
        return int(_U32.unpack_from(self._data, pos)[0])

    def uint64(self, i: int) -> int:
        if self._data is None or i < 0 or i >= self._length:
            return 0
        pos = self._offset + i * 8
        if pos + 8 > len(self._data):
            return 0
        return int(_U64.unpack_from(self._data, pos)[0])

    def object(self, i: int, elem_size: int) -> Object:
        """The i-th element of a fixed-stride struct list."""
        if self._data is None or i < 0 or i >= self._length:
            return Object(memoryview(b""), 0)
        return Object(self._data, self._offset + i * elem_size)

    def raw(self) -> _bytes:
        """The raw bytes of a flat byte list (stride 1)."""
        if self._data is None or self._offset + self._length > len(self._data):
            return b""
        return _bytes(self._data[self._offset : self._offset + self._length])

    # ── Variable-element accessors ─────────────────────────────────────────
    def bytes_at(self, i: int) -> _bytes:
        """The i-th payload of a variable-element list (random access, O(i))."""
        if self._data is None or i < 0 or i >= self._length:
            return b""
        data = self._data
        p = self._offset
        for _ in range(i):
            if p + 4 > len(data):
                return b""
            p += 4 + _u32(data, p)
        if p + 4 > len(data):
            return b""
        sz = _u32(data, p)
        start = p + 4
        end = start + sz
        if end > len(data):
            return b""
        return _bytes(data[start:end])

    def object_at(self, i: int) -> Object:
        """The i-th element of a variable-element list, parsed as an Object."""
        b = self.bytes_at(i)
        if not b:
            return Object(memoryview(b""), 0)
        try:
            return parse(b).root()
        except ZapError:
            return Object(memoryview(b""), 0)

    def each_bytes(self, fn: Callable[[int, bytes], bool]) -> None:
        """Walk a variable-element list once (O(N)), calling ``fn(i, payload)``.

        Single-pass counterpart to ``bytes_at(0..n-1)`` (which is O(N**2)).
        ``fn`` returns False to stop early. The walk also stops when the
        declared count is exhausted or the next entry would run off the buffer.
        """
        if self._data is None:
            return
        data = self._data
        p = self._offset
        for i in range(self._length):
            if p + 4 > len(data):
                return
            sz = _u32(data, p)
            start = p + 4
            end = start + sz
            if end > len(data):
                return
            if not fn(i, _bytes(data[start:end])):
                return
            p = end

    def each(self, fn: Callable[[int, Object], bool]) -> None:
        """Walk a variable-element list once, parsing each entry as an Object."""

        def _wrap(i: int, b: bytes) -> bool:
            try:
                elem = parse(b).root()
            except ZapError:
                elem = Object(memoryview(b""), 0)
            return fn(i, elem)

        self.each_bytes(_wrap)


# ── Builder ──────────────────────────────────────────────────────────────


class Builder:
    """Constructs ZAP messages.

    Build an object with :meth:`start_object`, set fields on the returned
    :class:`ObjectBuilder`, call :meth:`ObjectBuilder.finish_as_root`, then
    :meth:`finish` to get the wire bytes.
    """

    __slots__ = ("_buf", "_pos", "_root_offset")

    def __init__(self, capacity: int = 256):
        if capacity < HEADER_SIZE:
            capacity = 256
        self._buf = bytearray(capacity)
        self._pos = HEADER_SIZE  # data starts after the header
        self._root_offset = 0
        self._buf[0:4] = MAGIC
        _U16.pack_into(self._buf, 4, VERSION)

    def reset(self) -> None:
        """Reset for reuse (keeps the magic/version prefix)."""
        self._pos = HEADER_SIZE
        self._root_offset = 0
        for i in range(6, HEADER_SIZE):
            self._buf[i] = 0

    def _grow(self, n: int) -> None:
        need = self._pos + n
        if need <= len(self._buf):
            return
        new_cap = len(self._buf) * 2
        if new_cap < need:
            new_cap = need
        self._buf.extend(b"\x00" * (new_cap - len(self._buf)))

    def _align(self, alignment: int) -> None:
        padding = (alignment - (self._pos % alignment)) % alignment
        if padding:
            self._grow(padding)
            self._pos += padding  # buffer is already zero-filled

    def start_object(self, data_size: int) -> ObjectBuilder:
        """Start building an object whose fixed section is ``data_size`` bytes.

        The fixed section is reserved (zero-filled) up front, so fields may be
        set in any order and out-of-line tail data is appended after every
        fixed field rather than interleaved with one.
        """
        self._align(ALIGNMENT)
        ob = ObjectBuilder(self, self._pos, data_size)
        ob._ensure_field(data_size)
        return ob

    def write_bytes(self, data: bytes) -> int:
        """Write raw bytes (8-aligned) and return the offset (0 if empty)."""
        if not data:
            return 0
        self._align(ALIGNMENT)
        offset = self._pos
        self._grow(len(data))
        self._buf[self._pos : self._pos + len(data)] = data
        self._pos += len(data)
        return offset

    def write_text(self, s: str) -> int:
        return self.write_bytes(s.encode("utf-8"))

    def start_list(self, elem_size: int) -> ListBuilder:
        """Start building a list with the given fixed element stride."""
        self._align(ALIGNMENT)
        return ListBuilder(self, self._pos, elem_size)

    def finish(self) -> bytes:
        """Finalize the message and return the wire bytes."""
        _U32.pack_into(self._buf, 8, self._root_offset)
        _U32.pack_into(self._buf, 12, self._pos)
        return bytes(self._buf[: self._pos])

    def finish_with_flags(self, flags: int) -> bytes:
        """Finalize with the given header flags set."""
        _U16.pack_into(self._buf, 6, flags)
        return self.finish()


class ObjectBuilder:
    """Builds one ZAP object (struct). Obtain from :meth:`Builder.start_object`."""

    __slots__ = ("_b", "_start", "_data_size", "_deferred")

    def __init__(self, builder: Builder, start_pos: int, data_size: int):
        self._b = builder
        self._start = start_pos
        self._data_size = data_size
        # (field_offset, data) entries whose relative offset is patched in finish().
        self._deferred: list[tuple[int, bytes]] = []

    def _ensure_field(self, end_offset: int) -> None:
        needed = self._start + end_offset
        if needed > self._b._pos:
            self._b._grow(needed - self._b._pos)
            self._b._pos = needed  # buffer is zero-filled

    # Unsigned integers.
    def set_uint8(self, field_offset: int, v: int) -> None:
        self._ensure_field(field_offset + 1)
        self._b._buf[self._start + field_offset] = v & 0xFF

    def set_uint16(self, field_offset: int, v: int) -> None:
        self._ensure_field(field_offset + 2)
        _U16.pack_into(self._b._buf, self._start + field_offset, v & 0xFFFF)

    def set_uint32(self, field_offset: int, v: int) -> None:
        self._ensure_field(field_offset + 4)
        _U32.pack_into(self._b._buf, self._start + field_offset, v & 0xFFFFFFFF)

    def set_uint64(self, field_offset: int, v: int) -> None:
        self._ensure_field(field_offset + 8)
        _U64.pack_into(self._b._buf, self._start + field_offset, v & 0xFFFFFFFFFFFFFFFF)

    # Signed integers (stored two's-complement).
    def set_int8(self, field_offset: int, v: int) -> None:
        self.set_uint8(field_offset, v & 0xFF)

    def set_int16(self, field_offset: int, v: int) -> None:
        self.set_uint16(field_offset, v & 0xFFFF)

    def set_int32(self, field_offset: int, v: int) -> None:
        self.set_uint32(field_offset, v & 0xFFFFFFFF)

    def set_int64(self, field_offset: int, v: int) -> None:
        self.set_uint64(field_offset, v & 0xFFFFFFFFFFFFFFFF)

    # Floats / bool.
    def set_float32(self, field_offset: int, v: float) -> None:
        self._ensure_field(field_offset + 4)
        _F32.pack_into(self._b._buf, self._start + field_offset, v)

    def set_float64(self, field_offset: int, v: float) -> None:
        self._ensure_field(field_offset + 8)
        _F64.pack_into(self._b._buf, self._start + field_offset, v)

    def set_bool(self, field_offset: int, v: bool) -> None:
        self.set_uint8(field_offset, 1 if v else 0)

    def set_text(self, field_offset: int, v: str) -> None:
        self.set_bytes(field_offset, v.encode("utf-8"))

    def set_bytes(self, field_offset: int, v: bytes) -> None:
        """Set an out-of-line bytes field. The payload is laid down after the
        fixed section and its relative offset patched in :meth:`finish`."""
        self._ensure_field(field_offset + 8)  # relOffset + length slot
        if not v:
            _U32.pack_into(self._b._buf, self._start + field_offset, 0)
            _U32.pack_into(self._b._buf, self._start + field_offset + 4, 0)
            return
        self._deferred.append((field_offset, bytes(v)))
        _U32.pack_into(self._b._buf, self._start + field_offset + 4, len(v))

    def set_bytes_fixed(self, field_offset: int, v: bytes) -> None:
        """Copy ``len(v)`` bytes inline at ``field_offset`` (``bytes_fixed[N]``)."""
        if not v:
            return
        self._ensure_field(field_offset + len(v))
        self._b._buf[self._start + field_offset : self._start + field_offset + len(v)] = v

    def set_object(self, field_offset: int, obj_offset: int) -> None:
        """Set a nested-object pointer to the object at ``obj_offset``."""
        self._ensure_field(field_offset + 4)
        if obj_offset == 0:
            _U32.pack_into(self._b._buf, self._start + field_offset, 0)
            return
        rel = obj_offset - (self._start + field_offset)
        _U32.pack_into(self._b._buf, self._start + field_offset, rel & 0xFFFFFFFF)

    def set_list(self, field_offset: int, list_offset: int, length: int) -> None:
        """Set a list pointer (relative offset + element count)."""
        self._ensure_field(field_offset + 8)
        if list_offset == 0 or length == 0:
            _U32.pack_into(self._b._buf, self._start + field_offset, 0)
            _U32.pack_into(self._b._buf, self._start + field_offset + 4, 0)
            return
        rel = list_offset - (self._start + field_offset)
        _U32.pack_into(self._b._buf, self._start + field_offset, rel & 0xFFFFFFFF)
        _U32.pack_into(self._b._buf, self._start + field_offset + 4, length)

    def finish(self) -> int:
        """Lay down deferred payloads, patch their offsets, return the object offset."""
        self._ensure_field(self._data_size)
        for field_offset, data in self._deferred:
            data_pos = self._b._pos
            self._b._grow(len(data))
            self._b._buf[self._b._pos : self._b._pos + len(data)] = data
            self._b._pos += len(data)
            field_abs = self._start + field_offset
            rel = data_pos - field_abs
            _U32.pack_into(self._b._buf, field_abs, rel & 0xFFFFFFFF)
        return self._start

    def finish_as_root(self) -> int:
        """Finalize and set this object as the message root."""
        offset = self.finish()
        self._b._root_offset = offset
        return offset


class ListBuilder:
    """Builds one ZAP list. Obtain from :meth:`Builder.start_list`."""

    __slots__ = ("_b", "_start", "_elem_size", "_count")

    def __init__(self, builder: Builder, start_pos: int, elem_size: int):
        self._b = builder
        self._start = start_pos
        self._elem_size = elem_size
        self._count = 0

    def add_uint8(self, v: int) -> None:
        self._b._grow(1)
        self._b._buf[self._b._pos] = v & 0xFF
        self._b._pos += 1
        self._count += 1

    def add_uint32(self, v: int) -> None:
        self._b._grow(4)
        _U32.pack_into(self._b._buf, self._b._pos, v & 0xFFFFFFFF)
        self._b._pos += 4
        self._count += 1

    def add_uint64(self, v: int) -> None:
        self._b._grow(8)
        _U64.pack_into(self._b._buf, self._b._pos, v & 0xFFFFFFFFFFFFFFFF)
        self._b._pos += 8
        self._count += 1

    def add_bytes(self, data: bytes) -> None:
        """Append raw bytes to a flat byte list (count += len(data))."""
        self._b._grow(len(data))
        self._b._buf[self._b._pos : self._b._pos + len(data)] = data
        self._b._pos += len(data)
        self._count += len(data)

    def add_object_bytes(self, data: bytes) -> None:
        """Append one variable-length entry: ``[u32 length][data]`` (count += 1)."""
        self._b._grow(4 + len(data))
        _U32.pack_into(self._b._buf, self._b._pos, len(data))
        self._b._pos += 4
        self._b._buf[self._b._pos : self._b._pos + len(data)] = data
        self._b._pos += len(data)
        self._count += 1

    def finish(self) -> tuple[int, int]:
        """Return ``(offset, element_count)``."""
        return self._start, self._count

    def finish_offset(self) -> int:
        """Return just the list's start offset (count tracked externally)."""
        return self._start
