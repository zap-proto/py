# Code generated from capabilities.zap; DO NOT EDIT BY HAND.
# source: zap-spec/capabilities.zap (v1.1)
#
# Hand-port of the Go `capabilities_zap.go` generated views/builders to the
# Python `zap.wire` codec. The field offsets, struct sizes, and build order
# are byte-identical to the Go generator output — this is the contract that
# makes a Go-signed Capability decode and verify in Python (see the cross-lang
# KAT in tests/test_cap_kat.py). Offsets are frozen by the v1.1 wire format.
"""Generated zero-copy views and builders for the ZAP capability schema."""

from __future__ import annotations

from zap import wire

# ── Capability ─────────────────────────────────────────────────────────────
CAPABILITY_KIND_OFF = 0
CAPABILITY_TARGET_OFF = 4
CAPABILITY_HOLDER_OFF = 36
CAPABILITY_ISSUER_OFF = 68
CAPABILITY_PERMISSIONS_OFF = 100
CAPABILITY_PARENT_OFF = 108
CAPABILITY_ISSUED_AT_OFF = 140
CAPABILITY_EXPIRES_AT_OFF = 148
CAPABILITY_CAVEATS_OFF = 156
CAPABILITY_SIG_OFF = 164
CAPABILITY_SIZE = 3572

# ── Caveat ─────────────────────────────────────────────────────────────────
CAVEAT_KIND_OFF = 0
CAVEAT_VALUE_OFF = 4
CAVEAT_SIZE = 12

# ── Revocation ─────────────────────────────────────────────────────────────
REVOCATION_CAP_ID_OFF = 0
REVOCATION_REVOKED_AT_OFF = 32
REVOCATION_REVOKER_SIG_OFF = 40
REVOCATION_SIZE = 3448

#: Width of the signature footer (sig3408). Sized for FIPS 204 ML-DSA-65.
SIG_SIZE = 3408


def new_capability(
    *,
    kind: int,
    target: bytes,
    holder: bytes,
    issuer: bytes,
    permissions: int,
    parent: bytes,
    issued_at: int,
    expires_at: int,
    caveats: list[bytes],
    sig: bytes,
) -> bytes:
    """Build canonical ZAP wire bytes for a Capability.

    ``caveats`` are full ZAP-framed Caveat sub-messages (each from
    :func:`new_caveat`); they are length-prefixed into the Caveats list by
    ``add_object_bytes`` exactly as the Go ``ListBuilder.AddObjectBytes`` does.
    The build order (fixed fields, then the caveat list, then Sig) mirrors the
    Go generator so the heap layout — and therefore the on-wire bytes — is
    identical across runtimes.
    """
    b = wire.Builder(256)
    ob = b.start_object(CAPABILITY_SIZE)
    ob.set_uint32(CAPABILITY_KIND_OFF, kind)
    ob.set_bytes_fixed(CAPABILITY_TARGET_OFF, target)
    ob.set_bytes_fixed(CAPABILITY_HOLDER_OFF, holder)
    ob.set_bytes_fixed(CAPABILITY_ISSUER_OFF, issuer)
    ob.set_uint64(CAPABILITY_PERMISSIONS_OFF, permissions)
    ob.set_bytes_fixed(CAPABILITY_PARENT_OFF, parent)
    ob.set_uint64(CAPABILITY_ISSUED_AT_OFF, issued_at)
    ob.set_uint64(CAPABILITY_EXPIRES_AT_OFF, expires_at)
    caveats_lb = b.start_list(0)
    for elem in caveats:
        caveats_lb.add_object_bytes(elem)
    ob.set_list(CAPABILITY_CAVEATS_OFF, caveats_lb.finish_offset(), len(caveats))
    ob.set_bytes_fixed(CAPABILITY_SIG_OFF, sig)
    ob.finish_as_root()
    return b.finish()


def new_caveat(*, kind: int, value: bytes) -> bytes:
    """Build canonical ZAP wire bytes for a single Caveat sub-message."""
    b = wire.Builder(256)
    ob = b.start_object(CAVEAT_SIZE)
    ob.set_uint32(CAVEAT_KIND_OFF, kind)
    ob.set_bytes(CAVEAT_VALUE_OFF, value)
    ob.finish_as_root()
    return b.finish()


def new_revocation(*, cap_id: bytes, revoked_at: int, revoker_sig: bytes) -> bytes:
    """Build canonical ZAP wire bytes for a Revocation."""
    b = wire.Builder(256)
    ob = b.start_object(REVOCATION_SIZE)
    ob.set_bytes_fixed(REVOCATION_CAP_ID_OFF, cap_id)
    ob.set_uint64(REVOCATION_REVOKED_AT_OFF, revoked_at)
    ob.set_bytes_fixed(REVOCATION_REVOKER_SIG_OFF, revoker_sig)
    ob.finish_as_root()
    return b.finish()


__all__ = [
    "CAPABILITY_KIND_OFF",
    "CAPABILITY_TARGET_OFF",
    "CAPABILITY_HOLDER_OFF",
    "CAPABILITY_ISSUER_OFF",
    "CAPABILITY_PERMISSIONS_OFF",
    "CAPABILITY_PARENT_OFF",
    "CAPABILITY_ISSUED_AT_OFF",
    "CAPABILITY_EXPIRES_AT_OFF",
    "CAPABILITY_CAVEATS_OFF",
    "CAPABILITY_SIG_OFF",
    "CAPABILITY_SIZE",
    "CAVEAT_KIND_OFF",
    "CAVEAT_VALUE_OFF",
    "CAVEAT_SIZE",
    "REVOCATION_CAP_ID_OFF",
    "REVOCATION_REVOKED_AT_OFF",
    "REVOCATION_REVOKER_SIG_OFF",
    "REVOCATION_SIZE",
    "SIG_SIZE",
    "new_capability",
    "new_caveat",
    "new_revocation",
]
