"""Signers and the fail-closed verifier-side scheme dispatcher.

Ed25519 is mandatory-to-implement and the built-in bootstrap (RFC 8032 via the
``cryptography`` library). ML-DSA-65 (FIPS 204, via ``pqcrypto``) and secp256k1
ECDSA (via ``cryptography``) are real, fully-implemented schemes. Each signer
writes a 64/65/3309-byte primitive signature at the front of the SIG_SIZE
footer, zero-pads the middle, and stamps the algorithm tag at the final byte.

There are NO silent fallbacks and NO fabricated signatures. If a backend is
unavailable, every operation that needs it raises :class:`SchemeUnavailable`.
The verifier dispatch is fail-closed (SPEC §2.3 step 3c): the reserved tag
(0x00) and any tag this verifier does not implement are refused — never
downgraded to Ed25519.

These primitives live in the ``[crypto]`` extra; importing this module without
it is fine (the wire/codec layers stay pure-stdlib), but any sign/verify call
then raises a clear error.
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod

from ._codec import SIG_SIZE
from ._errors import SigMismatchError, UnhandledSchemeError
from ._kinds import ALG_TAG_OFFSET, Scheme, scheme_known

# ── Backend availability (mirrors zap.crypto: hard-fail, never fabricate) ───
try:
    from cryptography.exceptions import InvalidSignature as _InvalidSignature
    from cryptography.hazmat.primitives import hashes as _hashes
    from cryptography.hazmat.primitives.asymmetric import ec as _ec
    from cryptography.hazmat.primitives.asymmetric import utils as _ecutils
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey as _Ed25519PrivateKey,
    )
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PublicKey as _Ed25519PublicKey,
    )
    from cryptography.hazmat.primitives.serialization import Encoding as _Encoding
    from cryptography.hazmat.primitives.serialization import (
        PublicFormat as _PublicFormat,
    )

    _CRYPTOGRAPHY = True
except ImportError:  # pragma: no cover - exercised only without the extra
    _CRYPTOGRAPHY = False

try:
    from pqcrypto.sign import ml_dsa_65 as _mldsa  # type: ignore[import-untyped]

    _PQ = True
except ImportError:  # pragma: no cover - exercised only without the extra
    _mldsa = None
    _PQ = False

ED25519_SIG_LEN = 64
ED25519_PUB_LEN = 32
SECP256K1_SIG_LEN = 65  # R(32) || S(32) || v(1)
MLDSA65_SIG_LEN = 3309


class SchemeUnavailable(UnhandledSchemeError):
    """A required signature backend is not installed.

    A subclass of :class:`UnhandledSchemeError`, so a caller that treats *any*
    scheme failure as fail-closed catches an unavailable backend too — there is
    never a path where a missing dependency yields acceptance.
    """


def hash32(data: bytes) -> bytes:
    """The package's canonical 32-byte hash (SHA-256 per SPEC §4).

    SHA-256 is in every target language's stdlib, so CapIDs and pubkey hashes
    are trivially reproducible cross-language. Returns 32 raw bytes.
    """
    return hashlib.sha256(data).digest()


def _frame_sig(primitive: bytes, scheme: Scheme) -> bytes:
    """Place ``primitive`` at the front of a SIG_SIZE footer, zero-pad the
    middle, and stamp ``scheme`` at the final byte."""
    out = bytearray(SIG_SIZE)
    out[: len(primitive)] = primitive
    out[ALG_TAG_OFFSET] = int(scheme)
    return bytes(out)


# ── Signers ─────────────────────────────────────────────────────────────────


class Signer(ABC):
    """Abstracts the issuer's signing key.

    ``sign`` returns the full SIG_SIZE footer (primitive signature + zero pad +
    tag). ``public`` returns the 32-byte SHA-256 hash of the public key, which
    must equal the cap's Issuer field for verification to succeed.
    """

    @abstractmethod
    def sign(self, payload: bytes) -> bytes:
        """Sign ``payload`` and return the SIG_SIZE-byte footer."""

    @abstractmethod
    def public(self) -> bytes:
        """The 32-byte SHA-256 hash of this signer's public key."""

    @abstractmethod
    def public_key_bytes(self) -> bytes:
        """The raw public-key bytes a verifier resolves the issuer hash to."""


class Ed25519Signer(Signer):
    """Ed25519 signer (RFC 8032). The mandatory bootstrap scheme.

    Construct from a 32-byte seed (:meth:`from_seed`) for deterministic,
    reproducible keys (used by the cross-language KAT), or :meth:`generate` a
    fresh keypair.
    """

    __slots__ = ("_priv", "_pub_raw", "_pub_hash")

    def __init__(self, priv: object):
        _require_cryptography()
        self._priv = priv
        self._pub_raw: bytes = bytes(priv.public_key().public_bytes_raw())  # type: ignore[attr-defined]
        self._pub_hash = hash32(self._pub_raw)

    @classmethod
    def generate(cls) -> Ed25519Signer:
        _require_cryptography()
        return cls(_Ed25519PrivateKey.generate())

    @classmethod
    def from_seed(cls, seed: bytes) -> Ed25519Signer:
        """Deterministic key from a 32-byte seed (RFC 8032 §5.1.5)."""
        _require_cryptography()
        if len(seed) != 32:
            raise ValueError(f"ed25519 seed must be 32 bytes, got {len(seed)}")
        return cls(_Ed25519PrivateKey.from_private_bytes(seed))

    def sign(self, payload: bytes) -> bytes:
        sig = bytes(self._priv.sign(payload))  # type: ignore[attr-defined]
        if len(sig) != ED25519_SIG_LEN:
            raise SigMismatchError("ed25519 produced wrong signature size")
        return _frame_sig(sig, Scheme.ED25519)

    def public(self) -> bytes:
        return self._pub_hash

    def public_key_bytes(self) -> bytes:
        return self._pub_raw


class MLDSA65Signer(Signer):
    """ML-DSA-65 signer (FIPS 204 Level 3, via pqcrypto). 3309-byte signature."""

    __slots__ = ("_priv", "_pub_raw", "_pub_hash")

    def __init__(self, public_key: bytes, private_key: bytes):
        _require_pq()
        self._priv = private_key
        self._pub_raw = public_key
        self._pub_hash = hash32(public_key)

    @classmethod
    def generate(cls) -> MLDSA65Signer:
        _require_pq()
        pk, sk = _mldsa.generate_keypair()
        return cls(bytes(pk), bytes(sk))

    def sign(self, payload: bytes) -> bytes:
        sig = bytes(_mldsa.sign(self._priv, payload))
        if len(sig) != MLDSA65_SIG_LEN:
            raise SigMismatchError(
                f"ml-dsa-65 produced {len(sig)} bytes, expected {MLDSA65_SIG_LEN}"
            )
        return _frame_sig(sig, Scheme.MLDSA65)

    def public(self) -> bytes:
        return self._pub_hash

    def public_key_bytes(self) -> bytes:
        return self._pub_raw


class Secp256k1Signer(Signer):
    """secp256k1 ECDSA signer (via cryptography). 65-byte R||S||v signature.

    The ``v`` recovery byte is set to 0; the verifier in this package checks
    R||S against the public key directly (it does not recover the key from the
    signature), so ``v`` is informational and not load-bearing for our verify
    path.
    """

    __slots__ = ("_priv", "_pub_raw", "_pub_hash")

    def __init__(self, priv: object):
        _require_cryptography()
        self._priv = priv
        self._pub_raw: bytes = bytes(
            priv.public_key().public_bytes(  # type: ignore[attr-defined]
                _Encoding.X962, _PublicFormat.UncompressedPoint
            )
        )
        self._pub_hash = hash32(self._pub_raw)

    @classmethod
    def generate(cls) -> Secp256k1Signer:
        _require_cryptography()
        return cls(_ec.generate_private_key(_ec.SECP256K1()))

    def sign(self, payload: bytes) -> bytes:
        der = self._priv.sign(payload, _ec.ECDSA(_hashes.SHA256()))  # type: ignore[attr-defined]
        r, s = _ecutils.decode_dss_signature(der)
        primitive = r.to_bytes(32, "big") + s.to_bytes(32, "big") + b"\x00"
        return _frame_sig(primitive, Scheme.SECP256K1)

    def public(self) -> bytes:
        return self._pub_hash

    def public_key_bytes(self) -> bytes:
        return self._pub_raw


# ── Verifier-side primitives ────────────────────────────────────────────────


def _verify_ed25519(pub: bytes, payload: bytes, sig: bytes) -> None:
    """Verify a padded Ed25519 signature against a raw 32-byte pubkey."""
    _require_cryptography()
    if len(pub) != ED25519_PUB_LEN:
        raise SigMismatchError("ed25519 pubkey wrong size")
    try:
        _Ed25519PublicKey.from_public_bytes(pub).verify(sig[:ED25519_SIG_LEN], payload)
    except _InvalidSignature as exc:
        raise SigMismatchError("ed25519 signature does not verify") from exc


def _verify_mldsa65(pub: bytes, payload: bytes, sig: bytes) -> None:
    """Verify a padded ML-DSA-65 signature against a raw FIPS 204 pubkey."""
    _require_pq()
    if not _mldsa.verify(pub, payload, sig[:MLDSA65_SIG_LEN]):
        raise SigMismatchError("ml-dsa-65 signature does not verify")


def _verify_secp256k1(pub: bytes, payload: bytes, sig: bytes) -> None:
    """Verify a padded secp256k1 ECDSA signature (R||S||v) against a pubkey."""
    _require_cryptography()
    r = int.from_bytes(sig[0:32], "big")
    s = int.from_bytes(sig[32:64], "big")
    der = _ecutils.encode_dss_signature(r, s)
    try:
        key = _ec.EllipticCurvePublicKey.from_encoded_point(_ec.SECP256K1(), pub)
        key.verify(der, payload, _ec.ECDSA(_hashes.SHA256()))
    except (_InvalidSignature, ValueError) as exc:
        raise SigMismatchError("secp256k1 signature does not verify") from exc


#: Built-in verifiers for the schemes this runtime fully implements. Ed25519 is
#: the bootstrap; the others are equally real and verifiable in Python (a Go
#: verifier would wire an equivalent SchemeVerify hook to accept them).
_BUILTIN_VERIFIERS = {
    Scheme.ED25519: _verify_ed25519,
    Scheme.MLDSA65: _verify_mldsa65,
    Scheme.SECP256K1: _verify_secp256k1,
}


def verify_sig(
    pub: bytes,
    payload: bytes,
    sig: bytes,
    *,
    scheme_verify: object = None,
) -> None:
    """Fail-closed verifier-side dispatcher (SPEC §2.3 step 3c).

    1. The reserved tag (0x00) and any tag outside the known set are rejected
       immediately with :class:`UnhandledSchemeError`. No fallback. This is the
       fail-closed gate.
    2. If a ``scheme_verify`` hook is supplied, it gets first refusal on a known
       tag; returning anything other than ``UnhandledSchemeError`` (raising it)
       is final — this is how a consumer plugs an external primitive.
    3. Otherwise a built-in verifier handles Ed25519 / ML-DSA-65 / secp256k1.
       A known tag with no handler returns :class:`UnhandledSchemeError` — never
       a silent downgrade.

    Raises on failure; returns ``None`` on success.
    """
    if len(sig) != SIG_SIZE:
        raise SigMismatchError(f"signature footer must be {SIG_SIZE} bytes, got {len(sig)}")
    tag = sig[ALG_TAG_OFFSET]
    if not scheme_known(tag):
        # Fail-closed: reserved (0x00), unknown, or unassigned tag.
        raise UnhandledSchemeError(f"scheme tag {tag:#04x} not handled")
    scheme = Scheme(tag)
    if scheme_verify is not None:
        try:
            scheme_verify(scheme, pub, payload, sig)  # type: ignore[operator]
            return
        except UnhandledSchemeError:
            pass  # hook declined; fall through to built-ins
    handler = _BUILTIN_VERIFIERS.get(scheme)
    if handler is None:
        raise UnhandledSchemeError(f"scheme {scheme!r} has no built-in verifier")
    handler(pub, payload, sig)


# ── Backend guards ──────────────────────────────────────────────────────────


def _require_cryptography() -> None:
    if not _CRYPTOGRAPHY:
        raise SchemeUnavailable(
            "ed25519/secp256k1 backend unavailable - install with: pip install zap-proto[crypto]"
        )


def _require_pq() -> None:
    if not _PQ:
        raise SchemeUnavailable(
            "ml-dsa-65 backend unavailable - install with: pip install zap-proto[crypto]"
        )


__all__ = [
    "Signer",
    "Ed25519Signer",
    "MLDSA65Signer",
    "Secp256k1Signer",
    "SchemeUnavailable",
    "verify_sig",
    "hash32",
    "ED25519_SIG_LEN",
    "ED25519_PUB_LEN",
    "MLDSA65_SIG_LEN",
    "SECP256K1_SIG_LEN",
]
