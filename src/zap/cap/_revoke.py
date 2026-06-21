"""Revocation — produce and verify cap kill-entries.

A :class:`Revocation` states that a CapID is no longer valid. The signature is
over the 40-byte payload ``CapID || RevokedAt(u64-LE)``, occupying the SIG_SIZE
footer in the same shape as cap signatures (tag at the final byte). Only the
original Issuer may revoke. Verification dispatches on the tag, fail-closed.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from . import _codec as codec
from ._cap import Cap
from ._errors import ChainBrokenError, IssuerUnknownError, MissingSignerError
from ._kinds import Scheme
from ._sign import Signer, verify_sig
from ._verify import SchemeVerify

_U64 = struct.Struct("<Q")


def _revocation_payload(cap_id: bytes, revoked_at: int) -> bytes:
    """The 40 bytes that get signed: ``CapID(32) || RevokedAt(u64-LE)``."""
    return cap_id + _U64.pack(revoked_at)


@dataclass(frozen=True, slots=True)
class Revocation:
    """An on-the-wire kill-entry for a capability (and its descendants)."""

    cap_id: bytes
    revoked_at: int
    revoker_sig: bytes


def revoke(cap: Cap, now: int, signer: Signer) -> Revocation:
    """Produce a Revocation signed by ``signer``.

    The signer MUST be the cap's original Issuer — only the issuer can revoke.
    Raises :class:`ChainBrokenError` if the signer is not the issuer.
    """
    if signer is None:
        raise MissingSignerError("cap: signer required")
    if signer.public() != cap.issuer:
        raise ChainBrokenError("cap: signer is not the cap's issuer")
    cap_id = cap.id()
    sig = signer.sign(_revocation_payload(cap_id, now))
    return Revocation(cap_id=cap_id, revoked_at=now, revoker_sig=sig)


def verify_revocation(
    rev: Revocation,
    issuer_pub: bytes,
    *,
    scheme_verify: SchemeVerify | None = None,
) -> None:
    """Verify ``rev`` under the issuer's public key.

    Dispatches on the algorithm tag in ``rev.revoker_sig[ALG_TAG_OFFSET]``
    exactly as cap signatures do (scheme-aware, fail-closed). Wire a
    ``scheme_verify`` hook to accept primitives outside the built-in set. Raises
    on failure; returns ``None`` if valid.
    """
    if not issuer_pub:
        raise IssuerUnknownError("cap: issuer key unknown")
    verify_sig(
        issuer_pub,
        _revocation_payload(rev.cap_id, rev.revoked_at),
        rev.revoker_sig,
        scheme_verify=scheme_verify,
    )


def encode_revocation(rev: Revocation) -> bytes:
    """Marshal a Revocation into canonical ZAP wire bytes."""
    return codec.new_revocation(
        cap_id=rev.cap_id,
        revoked_at=rev.revoked_at,
        revoker_sig=rev.revoker_sig,
    )


def decode_revocation(buf: bytes) -> Revocation:
    """Parse a ZAP-framed Revocation buffer back into a :class:`Revocation`."""
    from zap import wire

    msg = wire.parse(buf)
    view = msg.root()
    return Revocation(
        cap_id=view.bytes_fixed(codec.REVOCATION_CAP_ID_OFF, 32),
        revoked_at=view.uint64(codec.REVOCATION_REVOKED_AT_OFF),
        revoker_sig=view.bytes_fixed(codec.REVOCATION_REVOKER_SIG_OFF, codec.SIG_SIZE),
    )


# Re-export for callers that pin scheme constants.
_ = Scheme

__all__ = [
    "Revocation",
    "revoke",
    "verify_revocation",
    "encode_revocation",
    "decode_revocation",
]
