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

__version__ = "0.2.1"
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
