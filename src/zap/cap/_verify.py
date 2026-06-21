"""The Verifier — single-cap Verify and full-chain VerifyChain (SPEC §2.3).

A :class:`Verifier` carries the policy dependencies validation needs: a
revocation lookup, an issuer-hash -> public-key resolver, and an optional
scheme hook for primitives outside the built-in set. Signature dispatch is
fail-closed (the reserved tag and unknown tags are refused, never downgraded).
"""

from __future__ import annotations

from collections.abc import Callable

from ._cap import Cap
from ._errors import (
    BadCaveatsError,
    ChainBrokenError,
    ExpiredError,
    HolderMismatchError,
    IssuerUnknownError,
    NotDelegableError,
    OpNotPermittedError,
    PermsExceedParentError,
    RevokedError,
    TargetMismatchError,
    UnknownCaveatError,
)
from ._kinds import PERM_ATTENUATE, CapKind, CaveatKind, Scheme
from ._sign import verify_sig

_ZERO32 = b"\x00" * 32

#: A revocation lookup: ``cap_id -> True`` means "reject". ``None`` => nothing
#: revoked.
IsRevoked = Callable[[bytes], bool]
#: Resolve a 32-byte issuer hash to its raw public-key bytes. MUST raise
#: :class:`IssuerUnknownError` (or return empty) for an unknown issuer.
IssuerKey = Callable[[bytes], bytes]
#: A scheme hook: ``(scheme, pub, payload, sig) -> None`` on success, raises
#: :class:`UnhandledSchemeError` to decline (falls back to the built-in path).
SchemeVerify = Callable[[Scheme, bytes, bytes, bytes], None]


class Verifier:
    """Validates capabilities and chains under a fixed policy."""

    __slots__ = ("is_revoked", "issuer_key", "scheme_verify")

    def __init__(
        self,
        *,
        issuer_key: IssuerKey | None = None,
        is_revoked: IsRevoked | None = None,
        scheme_verify: SchemeVerify | None = None,
    ):
        self.issuer_key = issuer_key
        self.is_revoked = is_revoked
        self.scheme_verify = scheme_verify

    def verify(self, cap: Cap, now: int) -> None:
        """Validate a single cap independent of chain context.

        Checks (in order): caveat framing parses, not expired at ``now``, not
        revoked, signature is valid for the cap's Issuer over its canonical
        bytes. Does NOT walk the parent chain — use :meth:`verify_chain`.
        Raises on any failure; returns ``None`` if acceptable.
        """
        # Walk the caveat list: catch bad framing AND refuse unknown kinds.
        # SPEC §2.3: verifiers MUST fail-closed on an unrecognized CaveatKind —
        # a caveat is a restriction; accepting it would silently ignore a
        # constraint the issuer intended (a privilege-escalation fail-open).
        for i in range(cap.num_caveats()):
            cav = cap.caveat_at(i)
            if cav is None:
                raise BadCaveatsError("cap: caveat block malformed")
            if cav.kind > CaveatKind.NONCE_HASH:
                raise UnknownCaveatError(f"cap: unknown caveat kind {cav.kind:#x}")

        # Expiry. 0 means never.
        exp = cap.expires_at
        if exp != 0 and now > exp:
            raise ExpiredError("cap: expired")

        # Revocation.
        cap_id = cap.id()
        if self.is_revoked is not None and self.is_revoked(cap_id):
            raise RevokedError("cap: revoked")

        # Signature.
        if self.issuer_key is None:
            raise IssuerUnknownError("cap: no issuer-key resolver")
        pub = self.issuer_key(cap.issuer)
        if not pub:
            raise IssuerUnknownError("cap: issuer key unknown")
        verify_sig(
            pub,
            cap.canonical_bytes(),
            cap.signature,
            scheme_verify=self.scheme_verify,
        )

    def verify_chain(
        self,
        leaf: Cap,
        chain: list[Cap],
        op: int,
        target: bytes,
        holder: bytes,
        now: int,
    ) -> None:
        """Validate a cap proof end-to-end (SPEC §2.3).

        ``chain`` is the parents nearest-to-leaf first: ``chain[0]`` is the
        leaf's parent, ``chain[-1]`` is the root. An empty chain means the leaf
        is itself a root.

        Enforces: leaf valid + grants ``op`` + matches ``target``/``holder``;
        each parent link valid on its own; each child's Parent equals its
        parent's id; permissions monotonically widen toward the root; each
        child's Issuer equals its parent's Holder; the delegation gate at every
        parent; Target invariance; and the root link has a zero Parent. Raises
        on any failure.
        """
        self.verify(leaf, now)
        if leaf.target != target:
            raise TargetMismatchError("cap: target does not match")
        if leaf.holder != holder:
            raise HolderMismatchError("cap: holder does not match")
        if (leaf.permissions & op) == 0:
            raise OpNotPermittedError("cap: op not in permission mask")

        prev = leaf
        last = len(chain) - 1
        for i, link in enumerate(chain):
            # The current cap's Parent must equal this link's id.
            if prev.parent != link.id():
                raise ChainBrokenError("cap: chain link broken (parent pointer)")
            # This link must be valid on its own merits.
            self.verify(link, now)
            # Authority widens toward the root: child perms subset of parent's;
            # child issuer == parent holder.
            if (prev.permissions & link.permissions) != prev.permissions:
                raise PermsExceedParentError("cap: permissions exceed parent")
            if prev.issuer != link.holder:
                raise ChainBrokenError("cap: chain link broken (issuer/holder)")
            # Delegation gate (SPEC §2.3 step 3d): the parent must have
            # authorized issuing children off it.
            if (link.permissions & PERM_ATTENUATE) == 0 and link.kind != int(CapKind.DELEGATE):
                raise NotDelegableError("cap: parent does not permit attenuation")
            # Target must remain identical as authority is attenuated.
            if link.target != target:
                raise TargetMismatchError("cap: target does not match")
            # The last link must be a root (Parent zero).
            if i == last and link.parent != _ZERO32:
                raise ChainBrokenError("cap: chain link broken (root not root)")
            prev = link

        # If chain is empty, the leaf must itself be a root.
        if not chain and leaf.parent != _ZERO32:
            raise ChainBrokenError("cap: chain link broken (leaf not root)")


__all__ = ["Verifier", "IsRevoked", "IssuerKey", "SchemeVerify"]
