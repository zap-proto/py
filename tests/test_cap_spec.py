"""SPEC conformance tests — mirror of go/cap/spec_test.go.

B3: signature scope is the SPEC §3 canonical bytes (header[0..164) + caveats),
not the whole buffer. B4/B6: scheme dispatch is fail-closed — the reserved tag
(0x00) and unknown tags are refused, never downgraded to Ed25519. Also covers
the ML-DSA-65 and secp256k1 schemes (real, fully verified in Python).
"""

from __future__ import annotations

import struct

import pytest

from zap import cap

pytest.importorskip("cryptography")


def _u64le(v: int) -> bytes:
    return struct.pack("<Q", v)


def _signer() -> cap.Ed25519Signer:
    return cap.Ed25519Signer.generate()


def _issuer_key(*signers: cap.Signer):
    table = {s.public(): s.public_key_bytes() for s in signers}
    return lambda h: table.get(h, b"")


def _sig_abs_off(raw: bytes) -> int:
    root_off = int.from_bytes(raw[8:12], "little")
    return root_off + cap._codec.CAPABILITY_SIG_OFF


def _perm_abs_off(raw: bytes) -> int:
    root_off = int.from_bytes(raw[8:12], "little")
    return root_off + cap._codec.CAPABILITY_PERMISSIONS_OFF


# ── B3: canonical-bytes shape ────────────────────────────────────────────────


def test_canonical_bytes_shape() -> None:
    signer = _signer()
    caveats = [
        cap.Caveat(int(cap.CaveatKind.MAX_AMOUNT), _u64le(7)),
        cap.Caveat(int(cap.CaveatKind.IP_CIDR), b"10.0.0.0/8"),
    ]
    c = cap.issue(
        cap.Issuance(
            kind=int(cap.CapKind.KMS_ACCESS),
            permissions=0xFF,
            expires_at=2000000000,
            caveats=caveats,
        ),
        signer,
    )
    got = c.canonical_bytes()

    # Reconstruct independently.
    root_off = int.from_bytes(c.raw[8:12], "little")
    hdr_len = cap._cap.SIGNED_HEADER_LEN
    want = bytearray(c.raw[root_off : root_off + hdr_len])
    for cv in caveats:
        want += struct.pack("<II", cv.kind, len(cv.value))
        want += cv.value
    assert got == bytes(want)

    want_len = hdr_len + (8 + 8) + (8 + len(b"10.0.0.0/8"))
    assert len(got) == want_len
    # Must NOT include the Sig footer.
    assert len(got) < hdr_len + cap.SIG_SIZE


def test_signature_excludes_sig_field() -> None:
    signer = _signer()
    c = cap.issue(
        cap.Issuance(kind=int(cap.CapKind.KMS_ACCESS), permissions=0xFF, expires_at=2000000000),
        signer,
    )
    before = c.canonical_bytes()
    # Scribble a zero-pad byte inside the Sig footer (after the 64-byte sig,
    # before the tag).
    raw = bytearray(c.raw)
    raw[_sig_abs_off(raw) + 100] ^= 0xFF
    c2 = cap.wrap(bytes(raw))
    assert before == c2.canonical_bytes()
    # And it still verifies (the scribble was outside the signed region + tag).
    v = cap.Verifier(issuer_key=_issuer_key(signer))
    v.verify(c2, 1)


def test_verify_detects_header_tamper() -> None:
    signer = _signer()
    c = cap.issue(
        cap.Issuance(kind=int(cap.CapKind.KMS_ACCESS), permissions=0xFF, expires_at=2000000000),
        signer,
    )
    raw = bytearray(c.raw)
    raw[_perm_abs_off(raw)] ^= 0x01
    tc = cap.wrap(bytes(raw))
    v = cap.Verifier(issuer_key=_issuer_key(signer))
    with pytest.raises(cap.SigMismatchError):
        v.verify(tc, 1)


# ── B6: cap signatures fail closed on scheme==0 / unknown ────────────────────


def test_verify_fails_closed_on_unknown_scheme() -> None:
    signer = _signer()
    c = cap.issue(cap.Issuance(permissions=1, expires_at=2000000000), signer)
    v = cap.Verifier(issuer_key=_issuer_key(signer))
    for tag in (0x00, 0x7F, 0xFF):
        raw = bytearray(c.raw)
        raw[_sig_abs_off(raw) + cap.ALG_TAG_OFFSET] = tag
        bad = cap.wrap(bytes(raw))
        with pytest.raises(cap.UnhandledSchemeError):
            v.verify(bad, 1)


def test_scheme_known_set() -> None:
    known = {
        int(cap.Scheme.SECP256K1),
        int(cap.Scheme.ED25519),
        int(cap.Scheme.MLDSA65),
        int(cap.Scheme.HYBRID),
    }
    for s in range(0x100):
        assert cap.scheme_known(s) == (s in known)
    assert not cap.scheme_known(int(cap.Scheme.RESERVED))


# ── B4: revocation dispatch is scheme-aware + fail-closed ────────────────────


def test_verify_revocation_scheme_aware() -> None:
    signer = _signer()
    c = cap.issue(cap.Issuance(permissions=1, expires_at=2000000000), signer)
    r = cap.revoke(c, 100, signer)
    # Bootstrap path: ed25519 tag, accepted.
    cap.verify_revocation(r, signer.public_key_bytes())

    # A revocation carrying a non-ed25519 tag must be routed to the hook.
    sig = bytearray(r.revoker_sig)
    sig[cap.ALG_TAG_OFFSET] = int(cap.Scheme.MLDSA65)
    r_pq = cap.Revocation(cap_id=r.cap_id, revoked_at=r.revoked_at, revoker_sig=bytes(sig))
    saw: list[cap.Scheme] = []

    def hook(scheme: cap.Scheme, pub: bytes, payload: bytes, s: bytes) -> None:
        saw.append(scheme)
        if scheme == cap.Scheme.MLDSA65:
            return  # pretend the PQ signature verifies
        raise cap.UnhandledSchemeError("decline")

    cap.verify_revocation(r_pq, signer.public_key_bytes(), scheme_verify=hook)
    assert saw == [cap.Scheme.MLDSA65]


def test_verify_revocation_fails_closed() -> None:
    signer = _signer()
    c = cap.issue(cap.Issuance(permissions=1, expires_at=2000000000), signer)
    r = cap.revoke(c, 100, signer)
    for tag in (0x00, 0x7F, 0xFF):
        sig = bytearray(r.revoker_sig)
        sig[cap.ALG_TAG_OFFSET] = tag
        bad = cap.Revocation(cap_id=r.cap_id, revoked_at=r.revoked_at, revoker_sig=bytes(sig))
        with pytest.raises(cap.UnhandledSchemeError):
            cap.verify_revocation(bad, signer.public_key_bytes())


# ── Multi-scheme: ML-DSA-65 and secp256k1 are real, end-to-end ───────────────


def test_mldsa65_issue_and_verify() -> None:
    pytest.importorskip("pqcrypto")
    signer = cap.MLDSA65Signer.generate()
    c = cap.issue(
        cap.Issuance(kind=int(cap.CapKind.KMS_SIGN), permissions=0xFF, expires_at=2000000000),
        signer,
    )
    assert c.signature[cap.ALG_TAG_OFFSET] == int(cap.Scheme.MLDSA65)
    v = cap.Verifier(issuer_key=_issuer_key(signer))
    v.verify(c, 1)  # no raise — real ML-DSA-65 verification

    # Tamper -> reject.
    raw = bytearray(c.raw)
    raw[_perm_abs_off(raw)] ^= 0x01
    with pytest.raises(cap.SigMismatchError):
        v.verify(cap.wrap(bytes(raw)), 1)


def test_secp256k1_issue_and_verify() -> None:
    signer = cap.Secp256k1Signer.generate()
    c = cap.issue(
        cap.Issuance(kind=int(cap.CapKind.ATS_ORDER), permissions=0xFF, expires_at=2000000000),
        signer,
    )
    assert c.signature[cap.ALG_TAG_OFFSET] == int(cap.Scheme.SECP256K1)
    v = cap.Verifier(issuer_key=_issuer_key(signer))
    v.verify(c, 1)  # no raise — real secp256k1 ECDSA verification

    raw = bytearray(c.raw)
    raw[_perm_abs_off(raw)] ^= 0x01
    with pytest.raises(cap.SigMismatchError):
        v.verify(cap.wrap(bytes(raw)), 1)


def test_mldsa65_attenuation_chain() -> None:
    """A full attenuation chain under ML-DSA-65 verifies end-to-end."""
    pytest.importorskip("pqcrypto")
    root = cap.MLDSA65Signer.generate()
    leaf = cap.MLDSA65Signer.generate()
    target = b"\x11" * 32
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
    leaf_cap = cap.attenuate(root_cap, leaf.public(), 0x0F, None, 0, root)
    v = cap.Verifier(issuer_key=_issuer_key(root, leaf))
    v.verify_chain(leaf_cap, [root_cap], 0x01, target, leaf.public(), 1700000000)


def test_scheme_unavailable_is_fail_closed_subclass() -> None:
    """SchemeUnavailable is an UnhandledSchemeError, so a missing backend can
    never be mistaken for acceptance by a fail-closed caller."""
    assert issubclass(cap.SchemeUnavailable, cap.UnhandledSchemeError)
    assert issubclass(cap.UnhandledSchemeError, cap.CapError)


# ── Adversarial fail-closed probes: no path returns "ok" on bad input ────────


def test_empty_pubkey_is_issuer_unknown() -> None:
    signer = _signer()
    c = cap.issue(cap.Issuance(permissions=1, expires_at=2000000000), signer)
    v = cap.Verifier(issuer_key=lambda _h: b"")
    with pytest.raises(cap.IssuerUnknownError):
        v.verify(c, 1)


def test_wrong_length_pubkey_is_sig_mismatch() -> None:
    signer = _signer()
    c = cap.issue(cap.Issuance(permissions=1, expires_at=2000000000), signer)
    v = cap.Verifier(issuer_key=lambda _h: b"\x00" * 16)
    with pytest.raises(cap.SigMismatchError):
        v.verify(c, 1)


def test_reserved_tag_blocked_before_scheme_hook() -> None:
    """An evil hook that accepts everything must NOT even be consulted for the
    reserved (0x00) tag — the fail-closed gate runs first."""
    signer = _signer()
    c = cap.issue(cap.Issuance(permissions=1, expires_at=2000000000), signer)
    raw = bytearray(c.raw)
    raw[_sig_abs_off(raw) + cap.ALG_TAG_OFFSET] = 0x00
    bad = cap.wrap(bytes(raw))
    called: list[cap.Scheme] = []

    def evil_hook(scheme: cap.Scheme, pub: bytes, payload: bytes, sig: bytes) -> None:
        called.append(scheme)  # tries to accept everything by returning

    v = cap.Verifier(issuer_key=_issuer_key(signer), scheme_verify=evil_hook)
    with pytest.raises(cap.UnhandledSchemeError):
        v.verify(bad, 1)
    assert called == []  # hook never reached


def test_unknown_tag_blocked_before_scheme_hook() -> None:
    signer = _signer()
    c = cap.issue(cap.Issuance(permissions=1, expires_at=2000000000), signer)
    raw = bytearray(c.raw)
    raw[_sig_abs_off(raw) + cap.ALG_TAG_OFFSET] = 0x55  # unassigned
    bad = cap.wrap(bytes(raw))
    called: list[cap.Scheme] = []

    def evil_hook(scheme: cap.Scheme, pub: bytes, payload: bytes, sig: bytes) -> None:
        called.append(scheme)

    v = cap.Verifier(issuer_key=_issuer_key(signer), scheme_verify=evil_hook)
    with pytest.raises(cap.UnhandledSchemeError):
        v.verify(bad, 1)
    assert called == []


def test_verify_sig_rejects_wrong_footer_length() -> None:
    with pytest.raises(cap.SigMismatchError):
        cap.verify_sig(b"\x00" * 32, b"payload", b"\x00" * 100)
