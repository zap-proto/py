"""Errors raised by the capability runtime.

Mirrors the Go ``cap`` error surface one-for-one so a reader who knows the Go
package finds the same failure taxonomy. Every check that can reject a cap
raises a distinct subclass of :class:`CapError`; nothing is silently swallowed.
"""

from __future__ import annotations


class CapError(Exception):
    """Base class for every capability-runtime error."""


class TooShortError(CapError):
    """Buffer is shorter than the wire framing requires."""


class BadMagicError(CapError):
    """Buffer does not begin with the ZAP magic."""


class BadCaveatsError(CapError):
    """The caveat block is malformed (an element failed to parse)."""


class UnknownCaveatError(CapError):
    """A caveat carries an unrecognized kind. Per SPEC §2.3 verifiers MUST
    refuse (fail-closed) — a caveat is a restriction that cannot be ignored."""


class SigMismatchError(CapError):
    """The signature does not verify against the issuer's public key."""


class ExpiredError(CapError):
    """The cap is past its ExpiresAt."""


class RevokedError(CapError):
    """The cap (or a chain ancestor) is on the revocation list."""


class ChainBrokenError(CapError):
    """A chain link is broken: parent pointer, issuer/holder linkage, or root."""


class PermsExceedParentError(CapError):
    """A child cap carries permission bits its parent does not."""


class NotDelegableError(CapError):
    """The parent does not permit attenuation (no PermAttenuate, not Delegate)."""


class OpNotPermittedError(CapError):
    """The requested op is not in the leaf's permission mask."""


class TargetMismatchError(CapError):
    """The cap's Target does not match the required target."""


class HolderMismatchError(CapError):
    """The cap's Holder does not match the required holder."""


class IssuerUnknownError(CapError):
    """The issuer's public key could not be resolved."""


class CaveatViolationError(CapError):
    """A caveat constraint was violated."""


class UnhandledSchemeError(CapError):
    """The Sig algorithm tag is reserved (0x00) or one this verifier does not
    implement. Fail-closed per SPEC §2.3 step 3c — never a silent downgrade.

    Also the value a scheme hook returns to decline a tag, so the dispatcher
    may fall through to the built-in Ed25519 bootstrap for SchemeEd25519.
    """


class MissingSignerError(CapError):
    """Issue/Attenuate/Revoke called without a signer. Every cap must be signed."""


__all__ = [
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
