"""
ZAP - Zero-Copy App Proto for Python

High-performance Cap'n Proto RPC for AI agent communication.
FastMCP-inspired API with decorator-based tool/resource/prompt registration.

Example:
    >>> from zap import ZAP
    >>>
    >>> app = ZAP("my-agent")
    >>>
    >>> @app.tool
    >>> def search(query: str) -> list[str]:
    ...     '''Search for content'''
    ...     return [f"Found: {query}"]
    >>>
    >>> if __name__ == "__main__":
    ...     app.run()
"""

# Wire-format submodule is pure-stdlib and always importable.
from zap import protocol  # noqa: F401

# The capnproto-backed RPC / identity / consensus / crypto modules require
# the optional `[capnp]` extra (pycapnp, pydantic, httpx, anyio + the `capnp`
# C library). Import lazily so a minimal install — for consumers that only
# need `from zap.protocol import ...` — does not fail at package import.
try:
    from zap.app import ZAP
    from zap.client import Client
    from zap.types import (
        Tool,
        ToolResult,
        Resource,
        ResourceContent,
        Prompt,
        PromptMessage,
        ServerInfo,
    )
    from zap.identity import DID, DIDMethod
    from zap.consensus import AgentConsensus, Query, Response, Vote
    from zap.crypto import (
        MLKEMKeyPair,
        MLDSAKeyPair,
        X25519KeyPair,
        HybridKeyExchange,
    )
except ImportError:
    # Capnp extras not installed. `zap.protocol` still works.
    pass

__version__ = "0.3.0"
__all__ = [
    # Core
    "ZAP",
    "Client",
    # Types
    "Tool",
    "ToolResult",
    "Resource",
    "ResourceContent",
    "Prompt",
    "PromptMessage",
    "ServerInfo",
    # Identity
    "DID",
    "DIDMethod",
    # Consensus
    "AgentConsensus",
    "Query",
    "Response",
    "Vote",
    # Crypto
    "MLKEMKeyPair",
    "MLDSAKeyPair",
    "X25519KeyPair",
    "HybridKeyExchange",
]
