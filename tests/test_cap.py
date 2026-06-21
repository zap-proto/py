"""Capability runtime tests — mirror of the Go cap_test.go + spec_test.go.

Happy paths, attenuation gating, chain walks, revocation, caveat encoding, and
the fail-closed scheme dispatch. The crypto primitives need the ``[crypto]``
extra; the whole module is skipped if it is absent (never a false green).
"""

from __future__ import annotations

import struct

import pytest

from zap import cap

# Skip the whole module if the crypto backend is missing — these tests sign and
# verify for real; a stub would be a lie.
pytest.importorskip("cryptography")


# ── helpers ──────────────────────────────────────────────────────────────────


def _u64le(v: int) -> bytes:
    return struct.pack("<Q", v)


def _u32pair(a: int, b: int) -> bytes:
    return struct.pack("<II", a, b)


def _signer() -> cap.Ed25519Signer:
    return cap.Ed25519Signer.generate()


def _issuer_key(*signers: cap.Signer):
    table = {s.public(): s.public_key_bytes() for s in signers}

    def resolve(h: bytes) -> bytes:
        pub = table.get(h)
        if pub is None:
            raise cap.IssuerUnknownError("unknown issuer")
        return pub

    return resolve


def _field_abs_off(raw: bytes, field_off: int) -> int:
    root_off = int.from_bytes(raw[8:12], "little")
    return root_off + field_off


def _sig_abs_off(raw: bytes) -> int:
    return _field_abs_off(raw, cap._codec.CAPABILITY_SIG_OFF)


# ── round trip ───────────────────────────────────────────────────────────────


def test_issue_round_trip() -> None:
    signer = _signer()
    target = bytes(range(32))
    holder = bytes((255 - i) & 0xFF for i in range(32))
    c = cap.issue(
        cap.Issuance(
            kind=int(cap.CapKind.IAM_SESSION),
            target=target,
            holder=holder,
            permissions=0xDEADBEEFCAFEBABE,
            issued_at=1700000000,
            expires_at=2000000000,
            caveats=[
                cap.Caveat(int(cap.CaveatKind.MAX_AMOUNT), _u64le(1_000_000)),
                cap.Caveat(int(cap.CaveatKind.RATE_LIMIT), _u32pair(60, 10)),
                cap.Caveat(int(cap.CaveatKind.IP_CIDR), b"10.0.0.0/8"),
            ],
        ),
        signer,
    )
    assert c.kind == int(cap.CapKind.IAM_SESSION)
    assert c.target == target
    assert c.holder == holder
    assert c.issuer == signer.public()
    assert c.permissions == 0xDEADBEEFCAFEBABE
    assert c.issued_at == 1700000000
    assert c.expires_at == 2000000000
    assert c.num_caveats() == 3

    cv0 = c.caveat_at(0)
    assert cv0 is not None and cv0.kind == int(cap.CaveatKind.MAX_AMOUNT)
    assert cv0.value == _u64le(1_000_000)
    cv2 = c.caveat_at(2)
    assert cv2 is not None and cv2.value == b"10.0.0.0/8"

    allcv = c.caveats()
    assert len(allcv) == 3 and allcv[2].kind == int(cap.CaveatKind.IP_CIDR)

    # Re-wrap round trips.
    rewrapped = cap.wrap(c.raw)
    assert rewrapped.kind == c.kind
    assert rewrapped.id() == c.id()


# ── verify accepts/rejects ───────────────────────────────────────────────────


def test_verify_accepts_fresh() -> None:
    signer = _signer()
    c = cap.issue(
        cap.Issuance(kind=int(cap.CapKind.KMS_ACCESS), permissions=0xFF, expires_at=2000000000),
        signer,
    )
    v = cap.Verifier(issuer_key=_issuer_key(signer))
    v.verify(c, 1700000000)  # no raise


def test_verify_rejects_expired() -> None:
    signer = _signer()
    c = cap.issue(
        cap.Issuance(kind=int(cap.CapKind.KMS_ACCESS), permissions=0xFF, expires_at=1700000000),
        signer,
    )
    v = cap.Verifier(issuer_key=_issuer_key(signer))
    with pytest.raises(cap.ExpiredError):
        v.verify(c, 1700000001)


def test_verify_rejects_revoked() -> None:
    signer = _signer()
    c = cap.issue(cap.Issuance(permissions=1), signer)
    v = cap.Verifier(issuer_key=_issuer_key(signer), is_revoked=lambda i: i == c.id())
    with pytest.raises(cap.RevokedError):
        v.verify(c, 1)


def test_verify_rejects_unknown_issuer() -> None:
    signer = _signer()
    other = _signer()
    c = cap.issue(cap.Issuance(permissions=1), signer)
    v = cap.Verifier(issuer_key=_issuer_key(other))  # knows other, not signer
    with pytest.raises(cap.IssuerUnknownError):
        v.verify(c, 1)


def test_verify_rejects_tampered_buffer() -> None:
    signer = _signer()
    c = cap.issue(cap.Issuance(permissions=1), signer)
    tampered = bytearray(c.raw)
    tampered[_field_abs_off(tampered, cap._codec.CAPABILITY_PERMISSIONS_OFF)] ^= 0x01
    tc = cap.wrap(bytes(tampered))
    v = cap.Verifier(issuer_key=_issuer_key(signer))
    with pytest.raises(cap.SigMismatchError):
        v.verify(tc, 1)


# ── attenuate ────────────────────────────────────────────────────────────────


def test_attenuate_intersects_permissions() -> None:
    root = _signer()
    child = _signer()
    target = bytes([0xAB]) + b"\x00" * 31
    parent = cap.issue(
        cap.Issuance(
            kind=int(cap.CapKind.ATS_ORDER),
            target=target,
            holder=root.public(),
            permissions=cap.PERM_ATTENUATE | 0b11110000,
            expires_at=2000000000,
        ),
        root,
    )
    leaf = cap.attenuate(
        parent,
        child.public(),
        0b10100110,
        [cap.Caveat(int(cap.CaveatKind.MAX_AMOUNT), _u64le(100))],
        0,
        root,
    )
    assert leaf.permissions == (0b11110000 & 0b10100110)
    assert leaf.parent == parent.id()
    assert leaf.issuer == root.public()  # child issuer == parent holder
    assert leaf.target == target
    assert leaf.expires_at == parent.expires_at


def test_attenuate_requires_parent_holder_key() -> None:
    root = _signer()
    imposter = _signer()
    holder = _signer()
    parent = cap.issue(
        cap.Issuance(permissions=0xFF, holder=root.public(), expires_at=2000000000), root
    )
    with pytest.raises(cap.ChainBrokenError):
        cap.attenuate(parent, holder.public(), 0xFF, None, 0, imposter)


def test_attenuate_caps_expiry_downward() -> None:
    root = _signer()
    holder = _signer()
    parent = cap.issue(
        cap.Issuance(permissions=cap.PERM_ATTENUATE | 0xFF, holder=root.public(), expires_at=1000),
        root,
    )
    leaf = cap.attenuate(parent, holder.public(), cap.PERM_ATTENUATE | 0xFF, None, 9999, root)
    assert leaf.expires_at == 1000  # clamped to parent


def test_attenuate_refuses_without_perm_attenuate() -> None:
    root = _signer()
    holder = _signer()
    parent = cap.issue(
        cap.Issuance(
            kind=int(cap.CapKind.IAM_SESSION),
            holder=root.public(),
            permissions=0xFF,  # no PERM_ATTENUATE, not DELEGATE
            expires_at=2000000000,
        ),
        root,
    )
    with pytest.raises(cap.NotDelegableError):
        cap.attenuate(parent, holder.public(), 0x0F, None, 0, root)


def test_attenuate_allowed_for_delegate_kind() -> None:
    root = _signer()
    holder = _signer()
    parent = cap.issue(
        cap.Issuance(
            kind=int(cap.CapKind.DELEGATE),
            holder=root.public(),
            permissions=0xFF,  # no PERM_ATTENUATE, but Kind == DELEGATE
            expires_at=2000000000,
        ),
        root,
    )
    # No raise: the kind itself authorizes delegation.
    cap.attenuate(parent, holder.public(), 0x0F, None, 0, root)


# ── verify chain ─────────────────────────────────────────────────────────────


def test_verify_chain_happy_path() -> None:
    root = _signer()
    mid = _signer()
    leaf = _signer()
    target = b"\x00" * 31 + bytes([0xEE])
    root_cap = cap.issue(
        cap.Issuance(
            kind=int(cap.CapKind.MPC_SIGN),
            target=target,
            holder=root.public(),
            permissions=cap.PERM_ATTENUATE | 0xFF,
            expires_at=2000000000,
        ),
        root,
    )
    mid_cap = cap.attenuate(root_cap, mid.public(), cap.PERM_ATTENUATE | 0x0F, None, 0, root)
    leaf_cap = cap.attenuate(mid_cap, leaf.public(), 0x07, None, 0, mid)
    v = cap.Verifier(issuer_key=_issuer_key(root, mid, leaf))
    v.verify_chain(leaf_cap, [mid_cap, root_cap], 0x04, target, leaf.public(), 1700000000)


def test_verify_chain_rejects_revoked_parent() -> None:
    root = _signer()
    mid = _signer()
    leaf = _signer()
    target = bytes([0x01]) + b"\x00" * 31
    root_cap = cap.issue(
        cap.Issuance(
            holder=root.public(),
            target=target,
            permissions=cap.PERM_ATTENUATE | 0xFF,
            expires_at=2000000000,
        ),
        root,
    )
    mid_cap = cap.attenuate(root_cap, mid.public(), cap.PERM_ATTENUATE | 0x0F, None, 0, root)
    leaf_cap = cap.attenuate(mid_cap, leaf.public(), 0x07, None, 0, mid)
    revoked = mid_cap.id()
    v = cap.Verifier(issuer_key=_issuer_key(root, mid, leaf), is_revoked=lambda i: i == revoked)
    with pytest.raises(cap.RevokedError):
        v.verify_chain(leaf_cap, [mid_cap, root_cap], 0x04, target, leaf.public(), 1700000000)


def test_verify_chain_rejects_broken_link() -> None:
    root = _signer()
    mid = _signer()
    leaf = _signer()
    other = _signer()
    target = b"\x00" * 32
    root_cap = cap.issue(
        cap.Issuance(
            holder=root.public(),
            target=target,
            permissions=cap.PERM_ATTENUATE | 0xFF,
            expires_at=2000000000,
        ),
        root,
    )
    mid_cap = cap.attenuate(root_cap, mid.public(), cap.PERM_ATTENUATE | 0x0F, None, 0, root)
    leaf_cap = cap.attenuate(mid_cap, leaf.public(), 0x07, None, 0, mid)
    bogus = cap.issue(
        cap.Issuance(
            holder=other.public(),
            target=target,
            permissions=cap.PERM_ATTENUATE | 0xFF,
            expires_at=2000000000,
        ),
        other,
    )
    v = cap.Verifier(issuer_key=_issuer_key(root, mid, leaf, other))
    with pytest.raises(cap.ChainBrokenError):
        v.verify_chain(leaf_cap, [bogus, root_cap], 0x04, target, leaf.public(), 1700000000)


def test_verify_chain_rejects_op_not_permitted() -> None:
    root = _signer()
    holder = _signer()
    target = b"\x00" * 32
    c = cap.issue(
        cap.Issuance(
            holder=holder.public(), target=target, permissions=0b0010, expires_at=2000000000
        ),
        root,
    )
    v = cap.Verifier(issuer_key=_issuer_key(root, holder))
    with pytest.raises(cap.OpNotPermittedError):
        v.verify_chain(c, [], 0b0100, target, holder.public(), 1)


def test_verify_chain_empty_chain_requires_root() -> None:
    root = _signer()
    holder = _signer()
    target = b"\x00" * 32
    c = cap.issue(
        cap.Issuance(
            holder=holder.public(), target=target, permissions=0xFF, expires_at=2000000000
        ),
        root,
    )
    v = cap.Verifier(issuer_key=_issuer_key(root, holder))
    v.verify_chain(c, [], 0x01, target, holder.public(), 1)  # root, ok

    # Pretend it has a parent: empty chain must now fail.
    tampered = bytearray(c.raw)
    tampered[_field_abs_off(tampered, cap._codec.CAPABILITY_PARENT_OFF)] = 0x99
    bad = cap.wrap(bytes(tampered))
    with pytest.raises(cap.CapError):
        v.verify_chain(bad, [], 0x01, target, holder.public(), 1)


def test_verify_chain_rejects_undelegated_parent() -> None:
    """Defense in depth: VerifyChain enforces the delegation gate even when a
    chain was forged past the mint-time gate (here via direct issue())."""
    root = _signer()
    mid = _signer()
    target = bytes([0x7E]) + b"\x00" * 31
    # Root WITHOUT PERM_ATTENUATE.
    root_cap = cap.issue(
        cap.Issuance(
            kind=int(cap.CapKind.IAM_SESSION),
            holder=root.public(),
            target=target,
            permissions=0x0F,
            expires_at=2000000000,
        ),
        root,
    )
    # Mint mid directly (bypassing attenuate's gate) with a correct chain shape.
    mid_cap = cap.issue(
        cap.Issuance(
            kind=int(cap.CapKind.IAM_SESSION),
            holder=mid.public(),
            target=target,
            permissions=0x07,
            parent=root_cap.id(),
            expires_at=2000000000,
        ),
        root,
    )
    v = cap.Verifier(issuer_key=_issuer_key(root, mid))
    with pytest.raises(cap.NotDelegableError):
        v.verify_chain(mid_cap, [root_cap], 0x01, target, mid.public(), 1700000000)


# ── revocation ───────────────────────────────────────────────────────────────


def test_revoke_and_verify() -> None:
    signer = _signer()
    c = cap.issue(cap.Issuance(permissions=1, expires_at=2000000000), signer)
    r = cap.revoke(c, 1234567890, signer)
    assert r.cap_id == c.id()
    assert r.revoked_at == 1234567890
    cap.verify_revocation(r, signer.public_key_bytes())  # no raise


def test_revoke_requires_issuer_key() -> None:
    signer = _signer()
    imposter = _signer()
    c = cap.issue(cap.Issuance(permissions=1, expires_at=2000000000), signer)
    with pytest.raises(cap.ChainBrokenError):
        cap.revoke(c, 1, imposter)


def test_verify_revocation_rejects_tampered() -> None:
    signer = _signer()
    c = cap.issue(cap.Issuance(permissions=1, expires_at=2000000000), signer)
    r = cap.revoke(c, 100, signer)
    tampered = cap.Revocation(cap_id=r.cap_id, revoked_at=200, revoker_sig=r.revoker_sig)
    with pytest.raises(cap.SigMismatchError):
        cap.verify_revocation(tampered, signer.public_key_bytes())


def test_revocation_encode_decode_round_trip() -> None:
    signer = _signer()
    c = cap.issue(cap.Issuance(permissions=1, expires_at=2000000000), signer)
    r = cap.revoke(c, 555, signer)
    decoded = cap.decode_revocation(cap.encode_revocation(r))
    assert decoded.cap_id == r.cap_id
    assert decoded.revoked_at == 555
    assert decoded.revoker_sig == r.revoker_sig
    cap.verify_revocation(decoded, signer.public_key_bytes())


# ── caveat encoding ──────────────────────────────────────────────────────────


def test_caveat_encoding_all_kinds() -> None:
    signer = _signer()
    chain_id = bytes(range(32))
    asset_id = bytes((0xA0 + (i & 0x0F)) for i in range(32))
    audience = bytes((0xC0 + (i & 0x0F)) for i in range(32))
    nonce = bytes((0xE0 + (i & 0x0F)) for i in range(32))
    cases = [
        cap.Caveat(int(cap.CaveatKind.EXPIRES_AT), _u64le(2000000000)),
        cap.Caveat(int(cap.CaveatKind.MAX_AMOUNT), _u64le(42)),
        cap.Caveat(int(cap.CaveatKind.DEST_CHAIN), chain_id),
        cap.Caveat(int(cap.CaveatKind.RATE_LIMIT), _u32pair(120, 30)),
        cap.Caveat(int(cap.CaveatKind.IP_CIDR), b"192.168.0.0/16"),
        cap.Caveat(int(cap.CaveatKind.ASSET_ID), asset_id),
        cap.Caveat(int(cap.CaveatKind.OP_ALLOW), _u64le(0xF0F0F0F0)),
        cap.Caveat(int(cap.CaveatKind.MAX_DEPTH), b"\x05"),
        cap.Caveat(int(cap.CaveatKind.AUDIENCE), audience),
        cap.Caveat(int(cap.CaveatKind.NONCE_HASH), nonce),
    ]
    c = cap.issue(cap.Issuance(permissions=1, expires_at=2000000000, caveats=cases), signer)
    assert c.num_caveats() == len(cases)
    for i, want in enumerate(cases):
        got = c.caveat_at(i)
        assert got is not None
        assert got.kind == want.kind
        assert got.value == want.value


# ── wire shape / framing ─────────────────────────────────────────────────────


def test_sig_size_v1_1() -> None:
    assert cap.SIG_SIZE == 3408
    assert cap.ALG_TAG_OFFSET == cap.SIG_SIZE - 1
    assert cap._codec.CAPABILITY_SIZE == 3572  # 164 + 3408
    assert cap._codec.REVOCATION_SIZE == 3448  # 40 + 3408


def test_issue_persists_alg_tag() -> None:
    signer = _signer()
    c = cap.issue(
        cap.Issuance(kind=int(cap.CapKind.IAM_SESSION), permissions=0xFF, expires_at=2000000000),
        signer,
    )
    sig = c.signature
    assert sig[cap.ALG_TAG_OFFSET] == int(cap.Scheme.ED25519)


def test_wrap_rejects_short_buffer() -> None:
    with pytest.raises(cap.TooShortError):
        cap.wrap(b"\x00" * 10)


def test_wrap_rejects_bad_magic() -> None:
    with pytest.raises(cap.BadMagicError):
        cap.wrap(b"\x00" * 512)


def test_wrap_rejects_truncated() -> None:
    signer = _signer()
    c = cap.issue(
        cap.Issuance(
            permissions=1,
            expires_at=2000000000,
            caveats=[cap.Caveat(int(cap.CaveatKind.MAX_AMOUNT), _u64le(1))],
        ),
        signer,
    )
    with pytest.raises(cap.CapError):
        cap.wrap(c.raw[:-1])
