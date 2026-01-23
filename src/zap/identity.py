"""W3C DID (Decentralized Identifier) support for ZAP."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class DIDMethod(str, Enum):
    """Supported DID methods."""

    LUX = "lux"
    KEY = "key"
    WEB = "web"


@dataclass
class DID:
    """
    W3C Decentralized Identifier.

    Supports:
    - did:lux - Lux blockchain-anchored DIDs
    - did:key - Self-certifying DIDs from cryptographic keys
    - did:web - DNS-based DIDs
    """

    method: DIDMethod
    id: str

    def __str__(self) -> str:
        return f"did:{self.method.value}:{self.id}"

    @classmethod
    def parse(cls, did_string: str) -> DID:
        """Parse a DID string."""
        if not did_string.startswith("did:"):
            raise ValueError(f"Invalid DID format: {did_string}")

        parts = did_string.split(":", 2)
        if len(parts) < 3:
            raise ValueError(f"Invalid DID format: {did_string}")

        method_str = parts[1]
        id_part = parts[2]

        try:
            method = DIDMethod(method_str)
        except ValueError:
            raise ValueError(f"Unsupported DID method: {method_str}")

        if not id_part:
            raise ValueError("DID identifier cannot be empty")

        return cls(method=method, id=id_part)

    @classmethod
    def from_public_key(cls, public_key: bytes) -> DID:
        """Create a did:key from a public key."""
        # Multibase encode with base58btc prefix
        encoded = _base58_encode(public_key)
        return cls(method=DIDMethod.KEY, id=f"z{encoded}")

    @classmethod
    def from_web(cls, domain: str, path: str = "") -> DID:
        """Create a did:web from a domain."""
        if "/" in domain:
            raise ValueError("Domain cannot contain '/'")
        if not domain:
            raise ValueError("Domain cannot be empty")

        id_part = domain
        if path:
            # Replace / with : in path
            id_part += ":" + path.replace("/", ":")

        return cls(method=DIDMethod.WEB, id=id_part)

    def is_valid(self) -> bool:
        """Check if the DID is valid."""
        return bool(self.id and self.method in DIDMethod)


@dataclass
class VerificationMethod:
    """Verification method in a DID Document."""

    id: str
    type: str
    controller: str
    public_key_multibase: str = ""
    public_key_jwk: dict[str, Any] | None = None
    blockchain_account_id: str = ""


@dataclass
class Service:
    """Service endpoint in a DID Document."""

    id: str
    type: str
    service_endpoint: str | list[str]


@dataclass
class DIDDocument:
    """W3C DID Document."""

    context: list[str] = field(
        default_factory=lambda: [
            "https://www.w3.org/ns/did/v1",
            "https://w3id.org/security/suites/ed25519-2020/v1",
        ]
    )
    id: str = ""
    controller: str = ""
    verification_method: list[VerificationMethod] = field(default_factory=list)
    authentication: list[str] = field(default_factory=list)
    assertion_method: list[str] = field(default_factory=list)
    key_agreement: list[str] = field(default_factory=list)
    capability_invocation: list[str] = field(default_factory=list)
    capability_delegation: list[str] = field(default_factory=list)
    service: list[Service] = field(default_factory=list)


def generate_document(did: DID) -> DIDDocument:
    """Generate a DID Document for a DID."""
    did_string = str(did)
    return DIDDocument(
        id=did_string,
        controller=did_string,
        verification_method=[
            VerificationMethod(
                id=f"{did_string}#keys-1",
                type="Multikey",
                controller=did_string,
                public_key_multibase=did.id if did.method == DIDMethod.KEY else "",
            )
        ],
        authentication=[f"{did_string}#keys-1"],
        assertion_method=[f"{did_string}#keys-1"],
        service=[
            Service(
                id=f"{did_string}#zap-agent",
                type="ZapAgent",
                service_endpoint=f"zap://{did_string}",
            )
        ],
    )


# Base58 encoding (Bitcoin alphabet)
_BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def _base58_encode(data: bytes) -> str:
    """Encode bytes to base58."""
    if not data:
        return ""

    # Count leading zeros
    leading_zeros = 0
    for byte in data:
        if byte == 0:
            leading_zeros += 1
        else:
            break

    # Convert to integer
    num = int.from_bytes(data, "big")

    # Convert to base58
    result = []
    while num > 0:
        num, remainder = divmod(num, 58)
        result.append(_BASE58_ALPHABET[remainder])

    # Add leading '1's for zeros
    return "1" * leading_zeros + "".join(reversed(result))


def _base58_decode(s: str) -> bytes:
    """Decode base58 to bytes."""
    if not s:
        return b""

    # Count leading '1's
    leading_ones = 0
    for char in s:
        if char == "1":
            leading_ones += 1
        else:
            break

    # Convert from base58
    num = 0
    for char in s:
        if char not in _BASE58_ALPHABET:
            raise ValueError(f"Invalid base58 character: {char}")
        num = num * 58 + _BASE58_ALPHABET.index(char)

    # Convert to bytes
    result = []
    while num > 0:
        result.append(num & 0xFF)
        num >>= 8

    return b"\x00" * leading_ones + bytes(reversed(result))
