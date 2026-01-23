"""ZAP Client for connecting to ZAP servers."""

from __future__ import annotations

import json
from typing import Any

import httpx

from zap.types import (
    Tool,
    ToolResult,
    Resource,
    ResourceContent,
    Prompt,
    PromptMessage,
    ServerInfo,
    Capabilities,
)


class Client:
    """
    ZAP Client for connecting to ZAP servers.

    Example:
        >>> async with Client("localhost:9999") as client:
        ...     tools = await client.list_tools()
        ...     result = await client.call_tool("search", {"query": "hello"})
    """

    def __init__(self, address: str, *, transport: str = "tcp"):
        """
        Initialize a ZAP client.

        Args:
            address: Server address (host:port)
            transport: Transport type (tcp, unix, websocket)
        """
        self.address = address
        self.transport = transport
        self._http = httpx.AsyncClient()
        self._connected = False

    async def __aenter__(self) -> Client:
        await self.connect()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()

    async def connect(self, name: str = "zap-client", version: str = "0.1.0") -> ServerInfo:
        """Connect to the ZAP server."""
        # TODO: Implement Cap'n Proto RPC connection
        # For now, return mock server info
        self._connected = True
        return ServerInfo(
            name="mock-server",
            version="0.1.0",
            capabilities=Capabilities(),
        )

    async def close(self) -> None:
        """Close the connection."""
        self._connected = False
        await self._http.aclose()

    async def list_tools(self) -> list[Tool]:
        """List available tools."""
        # TODO: Implement Cap'n Proto RPC call
        return []

    async def call_tool(self, name: str, args: dict[str, Any]) -> ToolResult:
        """Call a tool by name."""
        # TODO: Implement Cap'n Proto RPC call
        return ToolResult(id=name, error="Not implemented")

    async def list_resources(self) -> list[Resource]:
        """List available resources."""
        # TODO: Implement Cap'n Proto RPC call
        return []

    async def read_resource(self, uri: str) -> ResourceContent:
        """Read a resource by URI."""
        # TODO: Implement Cap'n Proto RPC call
        return ResourceContent(uri=uri, mime_type="text/plain", text="")

    async def list_prompts(self) -> list[Prompt]:
        """List available prompts."""
        # TODO: Implement Cap'n Proto RPC call
        return []

    async def get_prompt(
        self, name: str, args: dict[str, str] | None = None
    ) -> list[PromptMessage]:
        """Get a prompt by name with arguments."""
        # TODO: Implement Cap'n Proto RPC call
        return []

    async def log(
        self, level: str, message: str, data: dict[str, Any] | None = None
    ) -> None:
        """Send a log message to the server."""
        # TODO: Implement Cap'n Proto RPC call
        pass


async def connect(address: str, **kwargs: Any) -> Client:
    """Create and connect a ZAP client."""
    client = Client(address, **kwargs)
    await client.connect()
    return client
