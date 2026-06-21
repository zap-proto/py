"""Issue (mint a root cap) and Attenuate (derive a narrower child).

Both enforce SPEC invariants at MINT time so a cap that its own verifier would
reject is never produced (SPEC §7 — no "build relaxed, verify strict"
asymmetry). Attenuate gates on the parent carrying PERM_ATTENUATE (or being a
DELEGATE kind), intersects permissions, requires the signer to be the parent's
holder, and clamps expiry downward.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass, field

from . import _codec as codec
from ._cap import Cap, Caveat, wrap
from ._errors import ChainBrokenError, MissingSignerError, NotDelegableError
from ._kinds import PERM_ATTENUATE, CapKind
from ._sign import Signer

_ZERO32 = b"\x00" * 32


@dataclass(slots=True)
class Issuance:
    """A request to mint a capability."""

    kind: int = 0
    target: bytes = _ZERO32
    holder: bytes = _ZERO32
    permissions: int = 0
    parent: bytes = _ZERO32  # zero = root
    issued_at: int = 0  # 0 = use time.time()
    expires_at: int = 0  # 0 = no expiry
    caveats: list[Caveat] = field(default_factory=list)


def _pad32(b: bytes) -> bytes:
    """Normalize a 32-byte field: accept short/empty as zero-extended."""
    if len(b) == 32:
        return b
    if len(b) > 32:
        raise ValueError(f"id32 field must be <= 32 bytes, got {len(b)}")
    return b + b"\x00" * (32 - len(b))


def _build_cap_bytes(inp: Issuance, issuer: bytes, signer: Signer) -> bytes:
    """Serialize an Issuance to canonical ZAP bytes and sign it.

    The signed payload is the SPEC §3 canonical bytes, computed via
    :meth:`Cap.canonical_bytes` so the signer and verifier share one definition.
    First the buffer is built with a zeroed Sig (Sig is not in the signing
    scope), the canonical bytes are taken from that buffer, signed, and the
    SIG_SIZE-byte signature is patched into the Sig field in place.
    """
    caveat_bufs = [codec.new_caveat(kind=cv.kind, value=cv.value) for cv in inp.caveats]
    raw = bytearray(
        codec.new_capability(
            kind=inp.kind,
            target=_pad32(inp.target),
            holder=_pad32(inp.holder),
            issuer=_pad32(issuer),
            permissions=inp.permissions,
            parent=_pad32(inp.parent),
            issued_at=inp.issued_at,
            expires_at=inp.expires_at,
            caveats=caveat_bufs,
            sig=b"\x00" * codec.SIG_SIZE,
        )
    )
    # Compute the canonical signing bytes via the same code path the verifier
    # uses — no asymmetry between build and verify (SPEC §7).
    cap = wrap(bytes(raw))
    sig = signer.sign(cap.canonical_bytes())
    if len(sig) != codec.SIG_SIZE:
        raise ValueError(f"signer returned {len(sig)} bytes, expected {codec.SIG_SIZE}")
    # Patch the Sig field in place at root_off + sig_off.
    root_off = int.from_bytes(raw[8:12], "little")
    sig_off = root_off + codec.CAPABILITY_SIG_OFF
    raw[sig_off : sig_off + codec.SIG_SIZE] = sig
    return bytes(raw)


def issue(inp: Issuance, signer: Signer) -> Cap:
    """Mint a new root capability signed by ``signer``.

    The signer's public-key hash becomes the cap's Issuer. ``parent`` stays as
    supplied (zero for a true root). To derive a child from an existing parent,
    use :func:`attenuate`.
    """
    if signer is None:
        raise MissingSignerError("cap: signer required")
    if inp.issued_at == 0:
        inp.issued_at = int(time.time())
    return wrap(_build_cap_bytes(inp, signer.public(), signer))


def attenuate(
    parent: Cap,
    holder: bytes,
    permissions: int,
    caveats: Sequence[Caveat] | None,
    expires_at: int,
    signer: Signer,
) -> Cap:
    """Derive a child cap from ``parent`` by intersecting permissions.

    The child's Issuer = the parent's Holder; ``signer`` MUST hold the parent's
    holder key (the basis of chain validation: each link is signed by the
    previous holder's key). The child's Target equals the parent's (attenuation
    never broadens scope). ``permissions`` is intersected with the parent's.
    ``expires_at`` of 0 inherits the parent's expiry; non-zero overrides
    downward (the child cannot outlive the parent).

    Raises :class:`NotDelegableError` at mint time if the parent lacks
    PERM_ATTENUATE and is not a DELEGATE kind (SPEC §7 + §2.3 step 3d).
    """
    if signer is None:
        raise MissingSignerError("cap: signer required")
    if signer.public() != parent.holder:
        # Only the parent's holder can delegate authority downward.
        raise ChainBrokenError("cap: signer is not the parent's holder")
    # Mint-time delegation gate (SPEC §2.3 step 3d): the parent must carry
    # PERM_ATTENUATE or be a DELEGATE cap. Refuse to build a cap the verifier
    # would reject.
    if (parent.permissions & PERM_ATTENUATE) == 0 and parent.kind != int(CapKind.DELEGATE):
        raise NotDelegableError("cap: parent does not permit attenuation")

    # Expiry can only shrink: 0 inherits the parent's; a value above the
    # parent's is clamped down. The child cannot outlive the parent.
    parent_expiry = parent.expires_at
    if expires_at == 0 or (parent_expiry != 0 and expires_at > parent_expiry):
        expires_at = parent_expiry

    inp = Issuance(
        kind=parent.kind,
        target=parent.target,
        holder=holder,
        permissions=permissions & parent.permissions,
        parent=parent.id(),
        issued_at=int(time.time()),
        expires_at=expires_at,
        caveats=list(caveats) if caveats else [],
    )
    return wrap(_build_cap_bytes(inp, signer.public(), signer))


__all__ = ["Issuance", "issue", "attenuate"]
