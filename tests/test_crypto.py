"""Real post-quantum crypto — the two sides agree, verify rejects forgeries.

These tests require the ``[crypto]`` extra. They are skipped (not faked) when the
backend is unavailable; the module itself raises ``CryptoError`` rather than
returning fabricated bytes.
"""

import pytest

from zap import crypto
from zap.crypto import (
    CryptoError,
    HybridKeyExchange,
    MLDSAKeyPair,
    MLKEMKeyPair,
    X25519KeyPair,
)

pq = pytest.mark.skipif(not crypto.PQ_AVAILABLE, reason="pqcrypto not installed")
x = pytest.mark.skipif(not crypto.X25519_AVAILABLE, reason="cryptography not installed")


@pq
def test_mlkem_encapsulate_decapsulate_agree():
    kp = MLKEMKeyPair.generate()
    ciphertext, secret_a = kp.encapsulate()
    secret_b = kp.decapsulate(ciphertext)
    assert secret_a == secret_b
    assert len(secret_a) == crypto.SHARED_SECRET_SIZE


@pq
def test_mldsa_sign_verify():
    kp = MLDSAKeyPair.generate()
    sig = kp.sign(b"zap message")
    assert kp.verify(b"zap message", sig) is True


@pq
def test_mldsa_rejects_tampered_message():
    kp = MLDSAKeyPair.generate()
    sig = kp.sign(b"zap message")
    assert kp.verify(b"tampered", sig) is False


@pq
def test_mldsa_rejects_garbage_signature():
    """A random blob of the right length must NOT verify (no universal forgery)."""
    kp = MLDSAKeyPair.generate()
    forged = bytes(crypto.MLDSA_SIGNATURE_SIZE)
    assert kp.verify(b"zap message", forged) is False


@x
def test_x25519_exchange_agrees():
    a = X25519KeyPair.generate()
    b = X25519KeyPair.generate()
    assert a.exchange(b.public_key) == b.exchange(a.public_key)


@pq
@x
def test_hybrid_handshake_both_sides_agree():
    """The headline guarantee: initiator and responder derive the same secret."""
    a = HybridKeyExchange.generate()
    b = HybridKeyExchange.generate()
    a_x_pub, a_k_pub = a.initiate()
    b_x_pub, ciphertext, secret_responder = b.respond(a_x_pub, a_k_pub)
    secret_initiator = a.finalize(b_x_pub, ciphertext)
    assert secret_initiator == secret_responder
    assert len(secret_initiator) == crypto.SHARED_SECRET_SIZE


def test_hard_fail_when_unavailable(monkeypatch):
    """With the backend disabled, generate() raises CryptoError — never fakes."""
    monkeypatch.setattr(crypto, "PQ_AVAILABLE", False)
    with pytest.raises(CryptoError):
        MLKEMKeyPair.generate()
    with pytest.raises(CryptoError):
        MLDSAKeyPair.generate()
