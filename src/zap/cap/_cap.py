"""The ``Cap`` zero-copy view, CanonicalBytes, and CapID.

A :class:`Cap` is a parsed, read-only view over a capability buffer. Accessors
read straight from the wire bytes. :meth:`Cap.canonical_bytes` reproduces the
SPEC §3 signing scope *byte-for-byte* with the Go runtime, and :meth:`Cap.id`
is ``SHA-256(canonical_bytes || Sig)`` (SPEC §4) — the construction that binds
the chain (each child's Parent equals its parent's id).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from zap import wire

from . import _codec as codec
from ._codec import SIG_SIZE
from ._errors import BadCaveatsError, BadMagicError, TooShortError
from ._kinds import CaveatKind
from ._sign import hash32

_U32 = struct.Struct("<I")
_U64 = struct.Struct("<Q")

#: Length of the fixed-header prefix the signature covers: Capability[0..164),
#: i.e. Kind through the Caveats list pointer, NOT including Sig. Equal to the
#: Sig offset (Sig begins exactly where the signed header ends).
SIGNED_HEADER_LEN = codec.CAPABILITY_SIG_OFF


@dataclass(frozen=True, slots=True)
class Caveat:
    """One constraint attached to a capability (``Kind`` + opaque ``Value``)."""

    kind: int
    value: bytes


def _cap_root_off(raw: bytes) -> int:
    """Absolute offset of the Capability fixed header within ``raw``.

    The root offset is stored in the ZAP header at bytes [8:12], exactly as the
    Go ``capRootOff`` reads it. This is what makes CanonicalBytes align across
    runtimes regardless of heap layout.
    """
    return int(_U32.unpack_from(raw, 8)[0])


class Cap:
    """A zero-copy view over a capability buffer. Construct via :func:`wrap`."""

    __slots__ = ("_raw", "_view")

    def __init__(self, raw: bytes, view: wire.Object):
        self._raw = raw
        self._view = view

    # ── Raw / framing ───────────────────────────────────────────────────────
    @property
    def raw(self) -> bytes:
        """The underlying wire buffer."""
        return self._raw

    # ── Fixed-field accessors ───────────────────────────────────────────────
    @property
    def kind(self) -> int:
        return self._view.uint32(codec.CAPABILITY_KIND_OFF)

    @property
    def target(self) -> bytes:
        return self._view.bytes_fixed(codec.CAPABILITY_TARGET_OFF, 32)

    @property
    def holder(self) -> bytes:
        return self._view.bytes_fixed(codec.CAPABILITY_HOLDER_OFF, 32)

    @property
    def issuer(self) -> bytes:
        return self._view.bytes_fixed(codec.CAPABILITY_ISSUER_OFF, 32)

    @property
    def permissions(self) -> int:
        return self._view.uint64(codec.CAPABILITY_PERMISSIONS_OFF)

    @property
    def parent(self) -> bytes:
        return self._view.bytes_fixed(codec.CAPABILITY_PARENT_OFF, 32)

    @property
    def issued_at(self) -> int:
        return self._view.uint64(codec.CAPABILITY_ISSUED_AT_OFF)

    @property
    def expires_at(self) -> int:
        return self._view.uint64(codec.CAPABILITY_EXPIRES_AT_OFF)

    @property
    def signature(self) -> bytes:
        """The SIG_SIZE-byte signature footer."""
        return self._view.bytes_fixed(codec.CAPABILITY_SIG_OFF, SIG_SIZE)

    # ── Caveats ─────────────────────────────────────────────────────────────
    def num_caveats(self) -> int:
        return len(self._view.list(codec.CAPABILITY_CAVEATS_OFF))

    def caveats(self) -> list[Caveat]:
        """Decode the caveat list in one walk (list order preserved)."""
        lst = self._view.list(codec.CAPABILITY_CAVEATS_OFF)
        out: list[Caveat] = []
        for i in range(len(lst)):
            sub = lst.object_at(i)
            if sub.is_null():
                # A malformed element: stop. The eager check in `wrap` and the
                # verifier's own walk both surface this as BadCaveatsError.
                break
            out.append(
                Caveat(
                    kind=sub.uint32(codec.CAVEAT_KIND_OFF),
                    value=sub.bytes(codec.CAVEAT_VALUE_OFF),
                )
            )
        return out

    def caveat_at(self, i: int) -> Caveat | None:
        """The i-th caveat, or ``None`` if out of range / malformed."""
        lst = self._view.list(codec.CAPABILITY_CAVEATS_OFF)
        if i < 0 or i >= len(lst):
            return None
        sub = lst.object_at(i)
        if sub.is_null():
            return None
        return Caveat(
            kind=sub.uint32(codec.CAVEAT_KIND_OFF),
            value=sub.bytes(codec.CAVEAT_VALUE_OFF),
        )

    # ── Canonical bytes / id (SPEC §3 + §4) ─────────────────────────────────
    def canonical_bytes(self) -> bytes:
        """The exact bytes the signature is computed over (SPEC §3).

        ``Capability[0..164)`` read verbatim from the wire buffer, followed by
        each Caveat re-encoded as ``Kind:u32-LE || len(Value):u32-LE || Value``
        in list order. The fixed header (including the raw Caveats list pointer
        at [156..164)) is copied straight from the bytes, but the caveat
        section is RECOMPUTED — excluding the ZAP heap indirection bytes — so a
        tamperer cannot perturb the signature by rewriting heap layout and the
        signed bytes are identical across language runtimes. Excludes Sig.
        """
        hdr_off = _cap_root_off(self._raw)
        out = bytearray(self._raw[hdr_off : hdr_off + SIGNED_HEADER_LEN])
        for cv in self.caveats():
            out += _U32.pack(cv.kind)
            out += _U32.pack(len(cv.value))
            out += cv.value
        return bytes(out)

    def id(self) -> bytes:
        """The canonical 32-byte CapID: ``SHA-256(canonical_bytes || Sig)``.

        Per SPEC §4. Revocation records key on this; the chain walk matches each
        child's Parent to its parent's id.
        """
        return hash32(self.canonical_bytes() + self.signature)

    def __repr__(self) -> str:
        return (
            f"Cap(kind={self.kind:#x}, perms={self.permissions:#x}, "
            f"caveats={self.num_caveats()}, id={self.id().hex()[:16]}...)"
        )


def wrap(buf: bytes) -> Cap:
    """Parse a capability buffer into a zero-copy :class:`Cap` view.

    Validates ZAP framing (magic, version, declared size), checks the Sig field
    is within bounds, and eagerly walks the caveat list once to catch bad
    framing up front. Cryptographic verification lives in :mod:`zap.cap`'s
    Verifier — this only checks structure.
    """
    if len(buf) < wire.HEADER_SIZE:
        raise TooShortError("cap: buffer too short")
    try:
        msg = wire.parse(buf)
    except wire.InvalidMagic as exc:
        raise BadMagicError("cap: bad magic") from exc
    except wire.BufferTooSmall as exc:
        raise TooShortError("cap: buffer too short") from exc
    except wire.ZapError as exc:
        raise TooShortError(f"cap: {exc}") from exc

    view = msg.root()
    # The Sig field must occupy SIG_SIZE bytes inside the buffer.
    sig_abs = _cap_root_off(buf) + codec.CAPABILITY_SIG_OFF
    if sig_abs + SIG_SIZE > len(buf):
        raise TooShortError("cap: buffer too short")

    cap = Cap(buf, view)
    # Eager caveat walk: a non-empty list with a malformed element is rejected.
    lst = view.list(codec.CAPABILITY_CAVEATS_OFF)
    n = len(lst)
    for i in range(n):
        if lst.object_at(i).is_null():
            raise BadCaveatsError("cap: caveat block malformed")
    return cap


__all__ = [
    "Cap",
    "Caveat",
    "CaveatKind",
    "wrap",
    "SIGNED_HEADER_LEN",
]
