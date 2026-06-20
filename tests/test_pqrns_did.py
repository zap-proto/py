"""PQ-RNS DID KAT — verifies our compute_did matches the canonical
fixture published at zap-proto/rns/testdata/pqrns_kat.json."""

import base64
import hashlib
import json
import pathlib

KAT_PATH = pathlib.Path(__file__).parent / "pqrns_kat.json"


def compute_did(kem_pubkey: bytes, sig_pubkey: bytes) -> str:
    """Canonical did:zap computation. Must match every other SDK."""
    h = hashlib.sha3_256(kem_pubkey + sig_pubkey).digest()
    enc = base64.b32encode(h).decode("ascii").rstrip("=").lower()
    return "did:zap:" + enc


def test_pqrns_did_kat() -> None:
    kat = json.loads(KAT_PATH.read_text())
    canonical = kat["did_canonical"]

    kem_pk = bytes.fromhex(canonical["inputs"]["kem_pubkey_hex"])
    sig_pk = bytes.fromhex(canonical["inputs"]["sig_pubkey_hex"])

    assert len(kem_pk) == 1216
    assert len(sig_pk) == 1984

    got = compute_did(kem_pk, sig_pk)
    assert got == canonical["outputs"]["did"], (
        f"DID diverged:\n  got  {got}\n  want {canonical['outputs']['did']}"
    )
