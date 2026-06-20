"""Post-quantum cryptography for ZAP.

Real NIST FIPS 203 (ML-KEM-768) and FIPS 204 (ML-DSA-65) primitives via
``pqcrypto``, plus classical X25519 via ``cryptography``, and a hybrid
X25519+ML-KEM handshake whose final secret is derived with HKDF-SHA256.

There are NO silent fallbacks: if a backend is unavailable, every operation that
needs it raises :class:`CryptoError`. A handshake either runs on real
post-quantum primitives or fails loudly — it never returns fabricated bytes.

These primitives live in the ``[crypto]`` extra (``pip install
zap-proto[crypto]``); the core wire codec (:mod:`zap.wire`) has no dependency on
them.
"""

from __future__ import annotations

from dataclasses import dataclass

# Real ML-KEM-768 / ML-DSA-65 (FIPS 203 / 204) from pqcrypto. The standardized
# module names are ml_kem_768 / ml_dsa_65.
try:
    from pqcrypto.kem import ml_kem_768 as _mlkem  # type: ignore[import-untyped]
    from pqcrypto.sign import ml_dsa_65 as _mldsa  # type: ignore[import-untyped]

    PQ_AVAILABLE = True
    MLKEM_PUBLIC_KEY_SIZE = _mlkem.PUBLIC_KEY_SIZE
    MLKEM_SECRET_KEY_SIZE = _mlkem.SECRET_KEY_SIZE
    MLKEM_CIPHERTEXT_SIZE = _mlkem.CIPHERTEXT_SIZE
    MLDSA_PUBLIC_KEY_SIZE = _mldsa.PUBLIC_KEY_SIZE
    MLDSA_SECRET_KEY_SIZE = _mldsa.SECRET_KEY_SIZE
    MLDSA_SIGNATURE_SIZE = _mldsa.SIGNATURE_SIZE
except ImportError:  # pragma: no cover - exercised only without the extra
    _mlkem = None
    _mldsa = None
    PQ_AVAILABLE = False
    MLKEM_PUBLIC_KEY_SIZE = 1184
    MLKEM_SECRET_KEY_SIZE = 2400
    MLKEM_CIPHERTEXT_SIZE = 1088
    MLDSA_PUBLIC_KEY_SIZE = 1952
    MLDSA_SECRET_KEY_SIZE = 4032
    MLDSA_SIGNATURE_SIZE = 3309

try:
    from cryptography.hazmat.primitives import hashes as _hashes
    from cryptography.hazmat.primitives.asymmetric.x25519 import (
        X25519PrivateKey,
        X25519PublicKey,
    )
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    X25519_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only without the extra
    X25519PrivateKey = None  # type: ignore[assignment,misc]
    X25519PublicKey = None  # type: ignore[assignment,misc]
    X25519_AVAILABLE = False

X25519_PUBLIC_KEY_SIZE = 32
SHARED_SECRET_SIZE = 32

_HKDF_SALT = b"ZAP-HYBRID-HANDSHAKE-v1"
_HKDF_INFO = b"shared-secret"


class CryptoError(Exception):
    """A cryptographic operation failed or its backend is unavailable."""


def _require_pq() -> None:
    if not PQ_AVAILABLE:
        raise CryptoError(
            "post-quantum backend unavailable - install with: pip install zap-proto[crypto]"
        )


def _require_x25519() -> None:
    if not X25519_AVAILABLE:
        raise CryptoError(
            "X25519 backend unavailable - install with: pip install zap-proto[crypto]"
        )


@dataclass
class MLKEMKeyPair:
    """ML-KEM-768 key pair (FIPS 203) for post-quantum key encapsulation."""

    public_key: bytes
    private_key: bytes

    @classmethod
    def generate(cls) -> MLKEMKeyPair:
        _require_pq()
        pk, sk = _mlkem.generate_keypair()
        return cls(public_key=pk, private_key=sk)

    def encapsulate(self) -> tuple[bytes, bytes]:
        """Encapsulate to this public key; return ``(ciphertext, shared_secret)``."""
        _require_pq()
        if len(self.public_key) != MLKEM_PUBLIC_KEY_SIZE:
            raise CryptoError(
                f"invalid ML-KEM public key size: expected {MLKEM_PUBLIC_KEY_SIZE}, "
                f"got {len(self.public_key)}"
            )
        ciphertext, shared_secret = _mlkem.encrypt(self.public_key)
        return ciphertext, shared_secret

    def decapsulate(self, ciphertext: bytes) -> bytes:
        """Recover the shared secret from ``ciphertext`` using the private key."""
        _require_pq()
        if not self.private_key:
            raise CryptoError("no private key available for decapsulation")
        if len(ciphertext) != MLKEM_CIPHERTEXT_SIZE:
            raise CryptoError(
                f"invalid ML-KEM ciphertext size: expected {MLKEM_CIPHERTEXT_SIZE}, "
                f"got {len(ciphertext)}"
            )
        return bytes(_mlkem.decrypt(self.private_key, ciphertext))


@dataclass
class MLDSAKeyPair:
    """ML-DSA-65 key pair (FIPS 204) for post-quantum signatures."""

    public_key: bytes
    private_key: bytes

    @classmethod
    def generate(cls) -> MLDSAKeyPair:
        _require_pq()
        pk, sk = _mldsa.generate_keypair()
        return cls(public_key=pk, private_key=sk)

    def sign(self, message: bytes) -> bytes:
        """Sign ``message`` with the private key; return the detached signature."""
        _require_pq()
        if not self.private_key:
            raise CryptoError("no private key available for signing")
        return bytes(_mldsa.sign(self.private_key, message))

    def verify(self, message: bytes, signature: bytes) -> bool:
        """True iff ``signature`` is a valid ML-DSA-65 signature over ``message``."""
        _require_pq()
        if len(self.public_key) != MLDSA_PUBLIC_KEY_SIZE:
            raise CryptoError(
                f"invalid ML-DSA public key size: expected {MLDSA_PUBLIC_KEY_SIZE}, "
                f"got {len(self.public_key)}"
            )
        return bool(_mldsa.verify(self.public_key, message, signature))


@dataclass
class X25519KeyPair:
    """X25519 key pair for classical elliptic-curve Diffie-Hellman."""

    public_key: bytes
    private_key: bytes

    @classmethod
    def generate(cls) -> X25519KeyPair:
        _require_x25519()
        sk = X25519PrivateKey.generate()
        return cls(
            public_key=sk.public_key().public_bytes_raw(),
            private_key=sk.private_bytes_raw(),
        )

    def exchange(self, peer_public_key: bytes) -> bytes:
        """Diffie-Hellman against ``peer_public_key``; return the 32-byte secret."""
        _require_x25519()
        if len(peer_public_key) != X25519_PUBLIC_KEY_SIZE:
            raise CryptoError(
                f"invalid X25519 public key size: expected {X25519_PUBLIC_KEY_SIZE}, "
                f"got {len(peer_public_key)}"
            )
        sk = X25519PrivateKey.from_private_bytes(self.private_key)
        return sk.exchange(X25519PublicKey.from_public_bytes(peer_public_key))


def _derive_hybrid_secret(x25519_shared: bytes, mlkem_shared: bytes) -> bytes:
    """HKDF-SHA256 over ``x25519_shared || mlkem_shared`` -> 32-byte secret."""
    _require_x25519()
    hkdf = HKDF(
        algorithm=_hashes.SHA256(),
        length=SHARED_SECRET_SIZE,
        salt=_HKDF_SALT,
        info=_HKDF_INFO,
    )
    return hkdf.derive(x25519_shared + mlkem_shared)


@dataclass
class HybridKeyExchange:
    """Hybrid X25519 + ML-KEM-768 key exchange (defense in depth).

    Both an X25519 and an ML-KEM-768 secret are agreed independently, then mixed
    with HKDF-SHA256. If either primitive is broken, the other still protects the
    session. The two sides derive an identical secret (proven in the tests).

    Wire dance::

        a = HybridKeyExchange.generate()                    # initiator
        b = HybridKeyExchange.generate()                    # responder
        x_pub, k_pub, nonce = a.initiate()
        b_x_pub, ct, b_nonce, s_resp = b.respond(x_pub, k_pub, nonce)
        s_init = a.finalize(b_x_pub, ct, nonce, b_nonce)
        assert s_init == s_resp
    """

    x25519: X25519KeyPair
    mlkem: MLKEMKeyPair

    @classmethod
    def generate(cls) -> HybridKeyExchange:
        return cls(x25519=X25519KeyPair.generate(), mlkem=MLKEMKeyPair.generate())

    def initiate(self) -> tuple[bytes, bytes]:
        """Initiator's public material: ``(x25519_public, mlkem_public)``."""
        return self.x25519.public_key, self.mlkem.public_key

    def respond(
        self,
        peer_x25519_public: bytes,
        peer_mlkem_public: bytes,
    ) -> tuple[bytes, bytes, bytes]:
        """Responder side. Returns ``(x25519_public, mlkem_ciphertext, shared_secret)``.

        Encapsulates to the initiator's ML-KEM public key and runs X25519 against
        the initiator's X25519 public key, then derives the hybrid secret.
        """
        x25519_shared = self.x25519.exchange(peer_x25519_public)
        mlkem_ciphertext, mlkem_shared = MLKEMKeyPair(
            public_key=peer_mlkem_public, private_key=b""
        ).encapsulate()
        secret = _derive_hybrid_secret(x25519_shared, mlkem_shared)
        return self.x25519.public_key, mlkem_ciphertext, secret

    def finalize(
        self,
        peer_x25519_public: bytes,
        mlkem_ciphertext: bytes,
    ) -> bytes:
        """Initiator side. Decapsulates ``mlkem_ciphertext`` and derives the secret."""
        x25519_shared = self.x25519.exchange(peer_x25519_public)
        mlkem_shared = self.mlkem.decapsulate(mlkem_ciphertext)
        return _derive_hybrid_secret(x25519_shared, mlkem_shared)


__all__ = [
    "PQ_AVAILABLE",
    "X25519_AVAILABLE",
    "MLKEM_PUBLIC_KEY_SIZE",
    "MLKEM_SECRET_KEY_SIZE",
    "MLKEM_CIPHERTEXT_SIZE",
    "MLDSA_PUBLIC_KEY_SIZE",
    "MLDSA_SECRET_KEY_SIZE",
    "MLDSA_SIGNATURE_SIZE",
    "X25519_PUBLIC_KEY_SIZE",
    "SHARED_SECRET_SIZE",
    "CryptoError",
    "MLKEMKeyPair",
    "MLDSAKeyPair",
    "X25519KeyPair",
    "HybridKeyExchange",
]
