"""Cross-language Known-Answer Test — a Go-signed capability verifies in Python.

The fixture ``testdata/cap_go_kat.hex`` is the wire bytes of a Capability minted
and signed by the Go runtime (``github.com/zap-proto/go/cap``) with a FIXED
Ed25519 seed (32 bytes of 0x42) and fixed inputs. ``cap_go_kat.json`` carries
the seed, the raw public key, the Go-computed canonical bytes, and the
Go-computed CapID.

This is the interop proof. The same canonical bytes, the same CapID, and a
Go-produced signature that verifies under the Python verifier together
demonstrate that the two runtimes share one wire and one signing scope. A
byte-for-byte re-issue in Python (Ed25519 is deterministic per RFC 8032) closes
the loop in the other direction.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest

from zap import cap

pytest.importorskip("cryptography")

_TESTDATA = Path(__file__).parent / "testdata"


def _load_kat() -> dict[str, str]:
    with (_TESTDATA / "cap_go_kat.json").open() as f:
        data: dict[str, str] = json.load(f)
    # The .hex fixture is the authoritative wire bytes; assert the JSON agrees.
    hex_wire = (_TESTDATA / "cap_go_kat.hex").read_text().strip()
    assert hex_wire == data["wire_hex"], "fixture .hex and .json disagree on wire bytes"
    return data


def test_go_signed_cap_canonical_bytes_match() -> None:
    kat = _load_kat()
    c = cap.wrap(bytes.fromhex(kat["wire_hex"]))
    assert c.canonical_bytes() == bytes.fromhex(kat["canonical_hex"])


def test_go_signed_cap_id_matches() -> None:
    kat = _load_kat()
    c = cap.wrap(bytes.fromhex(kat["wire_hex"]))
    assert c.id().hex() == kat["capid_hex"]


def test_go_signed_cap_verifies_in_python() -> None:
    kat = _load_kat()
    c = cap.wrap(bytes.fromhex(kat["wire_hex"]))
    pub = bytes.fromhex(kat["pubkey_hex"])
    issuer_hash = bytes.fromhex(kat["issuer_hash"])
    assert c.issuer == issuer_hash
    assert c.issuer == cap.hash32(pub)

    def issuer_key(h: bytes) -> bytes:
        assert h == issuer_hash
        return pub

    v = cap.Verifier(issuer_key=issuer_key)
    v.verify(c, 1700000001)  # no raise => Go-signed cap verifies in Python


def test_go_signed_cap_tampered_variant_fails() -> None:
    kat = _load_kat()
    pub = bytes.fromhex(kat["pubkey_hex"])
    v = cap.Verifier(issuer_key=lambda _h: pub)

    raw = bytearray(bytes.fromhex(kat["wire_hex"]))
    root_off = int.from_bytes(raw[8:12], "little")
    # Flip a permission bit inside the signed header.
    raw[root_off + cap._codec.CAPABILITY_PERMISSIONS_OFF] ^= 0x01
    tampered = cap.wrap(bytes(raw))
    with pytest.raises(cap.SigMismatchError):
        v.verify(tampered, 1700000001)


def test_python_reissue_is_byte_identical_to_go() -> None:
    """Deterministic re-issue in Python yields the exact Go wire bytes.

    Ed25519 is deterministic (RFC 8032), so identical inputs + identical seed
    must produce identical signatures and therefore identical wire bytes —
    the strongest interop guarantee, both directions.
    """
    kat = _load_kat()
    signer = cap.Ed25519Signer.from_seed(bytes.fromhex(kat["seed_hex"]))
    assert signer.public_key_bytes() == bytes.fromhex(kat["pubkey_hex"])

    target = bytes(range(32))
    holder = bytes((0x80 + i) & 0xFF for i in range(32))
    inp = cap.Issuance(
        kind=int(cap.CapKind.IAM_SESSION),
        target=target,
        holder=holder,
        permissions=cap.PERM_ATTENUATE | 0x0F,
        parent=b"\x00" * 32,
        issued_at=1700000000,
        expires_at=2000000000,
        caveats=[
            cap.Caveat(int(cap.CaveatKind.MAX_AMOUNT), struct.pack("<Q", 1000000)),
            cap.Caveat(int(cap.CaveatKind.RATE_LIMIT), struct.pack("<II", 60, 10)),
            cap.Caveat(int(cap.CaveatKind.IP_CIDR), b"10.0.0.0/8"),
        ],
    )
    c = cap.issue(inp, signer)
    assert c.raw == bytes.fromhex(kat["wire_hex"])
    assert c.id().hex() == kat["capid_hex"]
