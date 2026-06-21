"""ZAP capability runtime — signed, attenuable tokens of authority.

A :class:`Cap` grants a holder permission to perform a bitmask of operations on
a target, with optional caveats. Caps form a chain: a parent's holder can issue
an attenuated child whose permissions are a subset of the parent's.
:meth:`Verifier.verify_chain` walks the chain back to a root, checking each
signature, the permission intersection, expiry, revocation, the delegation
gate, and target invariance.

This is a faithful Python port of the canonical Go runtime
(``github.com/zap-proto/go/cap``). The signing scope (:meth:`Cap.canonical_bytes`)
and the CapID (:meth:`Cap.id`) are byte-identical to Go's — a Go-signed cap
decodes and verifies here, and vice versa (proven by the cross-language KAT in
``tests/test_cap_kat.py``).

Schemes: Ed25519 (mandatory bootstrap), ML-DSA-65 (FIPS 204), and secp256k1
ECDSA are all fully implemented. Verifier dispatch is fail-closed (SPEC §2.3
step 3c): the reserved tag (0x00) and any tag the verifier does not implement
are refused — never silently downgraded. The signature primitives need the
``[crypto]`` extra; the wire/codec/canonical layers are pure stdlib.
"""

from __future__ import annotations

from ._cap import Cap, Caveat, wrap
from ._codec import SIG_SIZE
from ._errors import (
    BadCaveatsError,
    BadMagicError,
    CapError,
    CaveatViolationError,
    ChainBrokenError,
    ExpiredError,
    HolderMismatchError,
    IssuerUnknownError,
    MissingSignerError,
    NotDelegableError,
    OpNotPermittedError,
    PermsExceedParentError,
    RevokedError,
    SigMismatchError,
    TargetMismatchError,
    TooShortError,
    UnhandledSchemeError,
)
from ._issue import Issuance, attenuate, issue
from ._kinds import (
    ALG_TAG_OFFSET,
    KNOWN_SCHEMES,
    PERM_ATTENUATE,
    PERM_AUDIT,
    PERM_ROOT,
    CapKind,
    CaveatKind,
    Scheme,
    scheme_known,
)
from ._revoke import (
    Revocation,
    decode_revocation,
    encode_revocation,
    revoke,
    verify_revocation,
)
from ._sign import (
    Ed25519Signer,
    MLDSA65Signer,
    SchemeUnavailable,
    Secp256k1Signer,
    Signer,
    hash32,
    verify_sig,
)
from ._verify import Verifier

__all__ = [
    # Core view + canonical bytes + id
    "Cap",
    "Caveat",
    "wrap",
    # Issue / attenuate
    "Issuance",
    "issue",
    "attenuate",
    # Verify
    "Verifier",
    # Revoke
    "Revocation",
    "revoke",
    "verify_revocation",
    "encode_revocation",
    "decode_revocation",
    # Signers + dispatch
    "Signer",
    "Ed25519Signer",
    "MLDSA65Signer",
    "Secp256k1Signer",
    "SchemeUnavailable",
    "verify_sig",
    "hash32",
    # Enums / constants
    "Scheme",
    "CapKind",
    "CaveatKind",
    "KNOWN_SCHEMES",
    "scheme_known",
    "ALG_TAG_OFFSET",
    "SIG_SIZE",
    "PERM_ATTENUATE",
    "PERM_AUDIT",
    "PERM_ROOT",
    # Errors
    "CapError",
    "TooShortError",
    "BadMagicError",
    "BadCaveatsError",
    "SigMismatchError",
    "ExpiredError",
    "RevokedError",
    "ChainBrokenError",
    "PermsExceedParentError",
    "NotDelegableError",
    "OpNotPermittedError",
    "TargetMismatchError",
    "HolderMismatchError",
    "IssuerUnknownError",
    "CaveatViolationError",
    "UnhandledSchemeError",
    "MissingSignerError",
]
