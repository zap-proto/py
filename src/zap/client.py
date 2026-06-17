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


# ── Router client — talk to the local zapd daemon over its UDS ─────────────

import os as _os
import socket as _socket
import threading as _threading

from zap import frame as _frame
from zap.frame import (
    ERROR as _ERROR,
    HELLO as _HELLO,
    PROVIDERS as _PROVIDERS,
    PROVIDERS_LIST as _PROVIDERS_LIST,
    RESPONSE as _RESPONSE,
    ROLE_CONSUMER as _ROLE_CONSUMER,
    ROLE_PROVIDER as _ROLE_PROVIDER,
    ROLE_ROUTER as _ROLE_ROUTER,
    ROUTE as _ROUTE,
    WELCOME as _WELCOME,
    Frame as _Frame,
)

_ROLES = {"consumer": _ROLE_CONSUMER, "provider": _ROLE_PROVIDER, "router": _ROLE_ROUTER}


class ZapClient:
    """Synchronous client for the local ``zapd`` router.

    >>> c = ZapClient.connect(id="consumer:hanzo-mcp/123", role="consumer")
    >>> [p.id for p in c.providers_list(kind="browser")]
    ['browser:chrome/dbc/default']
    >>> c.route(to="browser:chrome/dbc/default", payload=frame.encode_cmd("Target.getTargets", {}))
    b'{"targetInfos": ...}'
    """

    def __init__(self, sock: "_socket.socket", node_id: str):
        self._sock = sock
        self.node_id = node_id
        self._lock = _threading.Lock()

    @classmethod
    def connect(
        cls,
        id: str | None = None,
        role: str = "consumer",
        brand: str = "hanzo",
        caps=(),
        path: str | None = None,
        timeout: float = 10.0,
    ) -> "ZapClient":
        node_id = id or f"consumer:zap/{_os.getpid()}"
        s = _socket.socket(_socket.AF_UNIX)
        s.settimeout(timeout)
        s.connect(path or _frame.socket_path())
        c = cls(s, node_id)
        c.hello(role=role, id=node_id, brand=brand, caps=caps)
        return c

    def hello(self, role: str = "consumer", id: str | None = None, brand: str = "hanzo", caps=()) -> None:
        if id:
            self.node_id = id
        r = _ROLES.get(role, _ROLE_CONSUMER) if isinstance(role, str) else role
        self._sock.sendall(_Frame(_HELLO, self.node_id, "", _frame.encode_hello(r, brand, list(caps))).encode())
        self._read_until(_WELCOME)

    def providers_list(self, kind: str = "", brand: str = "") -> list:
        """List providers. ``kind`` filters by id prefix (e.g. ``browser``)."""
        with self._lock:
            payload = _frame._put_str(brand) if brand else b""
            self._sock.sendall(_Frame(_PROVIDERS_LIST, self.node_id, "", payload).encode())
            f = self._read_until(_PROVIDERS)
            provs = _frame.parse_providers(f.payload)
            return [p for p in provs if not kind or p.id.startswith(kind + ":")]

    def route(self, to: str, payload: bytes, timeout: float = 30.0) -> bytes:
        """Route an opaque payload to ``to`` and return its RESPONSE payload."""
        with self._lock:
            self._sock.settimeout(timeout)
            self._sock.sendall(_Frame(_ROUTE, self.node_id, to, payload).encode())
            return self._read_until(_RESPONSE, frm=to).payload

    def close(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass

    def _read_until(self, typ: int, frm: str | None = None) -> "_Frame":
        for _ in range(100):
            f = _Frame.read(self._sock)
            if f.typ == typ and (frm is None or f.frm == frm):
                return f
            if f.typ == _ERROR:
                raise RuntimeError(f.payload.decode(errors="replace"))
        raise TimeoutError(f"zap: no frame type {typ}")
