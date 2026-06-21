"""ZAP capability enums — the normative wire contract.

Constants are mirrored verbatim from ``zap-spec/capabilities_kinds.md`` (which
is *part of the wire contract*) and the Go ``cap`` package. Changing any value
here breaks cross-language interop. Schemes, kinds, caveat kinds, and the
cross-cutting permission bits are all frozen at v1.1.
"""

from __future__ import annotations

from enum import IntEnum

#: Offset of the algorithm-tag byte within the SIG_SIZE footer. The byte at
#: ``Sig[ALG_TAG_OFFSET]`` selects the verifier primitive and is inside the
#: signed payload (a tag flip changes the signature, caught by mismatch).
from ._codec import SIG_SIZE

ALG_TAG_OFFSET = SIG_SIZE - 1


class Scheme(IntEnum):
    """Wire-level signature algorithm tag (``Sig[ALG_TAG_OFFSET]``, u8).

    Verifiers fail-closed on :attr:`RESERVED` (0x00) and on any value not
    enumerated here (SPEC §2.3 step 3c).
    """

    RESERVED = 0x00  # MUST NOT appear; verifiers refuse (catches zero-filled footer)
    SECP256K1 = 0x01  # 65-byte secp256k1 ECDSA (R||S||v)
    ED25519 = 0x02  # 64-byte Ed25519 (RFC 8032)
    MLDSA65 = 0x03  # 3309-byte FIPS 204 Level-3 ML-DSA-65
    HYBRID = 0x04  # Ed25519 || ML-DSA-65 concatenated


#: The exact set of scheme tags a verifier may accept (SPEC §2.3 step 3c).
#: RESERVED (0x00) and any unassigned tag are NOT known -> fail-closed.
KNOWN_SCHEMES: frozenset[Scheme] = frozenset(
    {Scheme.SECP256K1, Scheme.ED25519, Scheme.MLDSA65, Scheme.HYBRID}
)


def scheme_known(tag: int) -> bool:
    """Whether ``tag`` is a registered signature scheme (fail-closed default)."""
    try:
        return Scheme(tag) in KNOWN_SCHEMES
    except ValueError:
        return False


class CapKind(IntEnum):
    """The kind of authority a capability confers (``Capability.Kind``, u32)."""

    RESERVED = 0x00
    IAM_SESSION = 0x01
    IAM_API_KEY = 0x02
    KMS_ACCESS = 0x10
    KMS_SIGN = 0x11
    MPC_SIGN = 0x20
    ATS_ORDER = 0x30
    BRIDGE_XFER = 0x40
    STAKE = 0x50
    DELEGATE = 0xFF


class CaveatKind(IntEnum):
    """The kind of constraint attached to a capability (``Caveat.Kind``, u32)."""

    EXPIRES_AT = 0x00
    MAX_AMOUNT = 0x01
    DEST_CHAIN = 0x02
    RATE_LIMIT = 0x03
    IP_CIDR = 0x04
    ASSET_ID = 0x05
    OP_ALLOW = 0x06
    MAX_DEPTH = 0x07
    AUDIENCE = 0x08
    NONCE_HASH = 0x09


# ── Cross-cutting permission bits (top 32, identical across every CapKind) ──
# The bottom 32 bits are per-CapKind and owned by each consumer; only the
# cross-cutting bits are normative wire-wide (capabilities_kinds.md).

#: The holder may mint child caps whose permissions are a subset of this cap's.
#: SPEC §2.3 step 3d: a parent MUST carry this (or be CapKind.DELEGATE) for the
#: verifier to accept any attenuation off it.
PERM_ATTENUATE = 1 << 32
#: The holder may read the audit trail for Target.
PERM_AUDIT = 1 << 33
#: Root-of-trust marker; set on root caps only.
PERM_ROOT = 1 << 63


__all__ = [
    "ALG_TAG_OFFSET",
    "SIG_SIZE",
    "Scheme",
    "KNOWN_SCHEMES",
    "scheme_known",
    "CapKind",
    "CaveatKind",
    "PERM_ATTENUATE",
    "PERM_AUDIT",
    "PERM_ROOT",
]
