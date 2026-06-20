"""ZAP clients.

:class:`Client` is a real synchronous ZAP RPC client over TCP (it speaks the
:mod:`zap.rpc` envelope and dispatches the ``Zap`` method ordinals).
:class:`ZapClient` is the router client that talks to the local ``zapd`` daemon
over its Unix domain socket.

Both are pure stdlib — no third-party dependency on the import path.
"""

from __future__ import annotations

import contextlib
import os
import socket
import threading
from collections.abc import Iterable
from typing import Any

from zap import frame
from zap.frame import (
    ERROR,
    HELLO,
    PROVIDERS,
    PROVIDERS_LIST,
    RESPONSE,
    ROLE_CONSUMER,
    ROLE_PROVIDER,
    ROLE_ROUTER,
    ROUTE,
    WELCOME,
    Frame,
    Provider,
)
from zap.rpc import Client as _RpcClient
from zap.rpc import Method
from zap.types import (
    Prompt,
    PromptArgument,
    PromptMessage,
    Resource,
    ResourceContent,
    ServerInfo,
    Tool,
    ToolResult,
)

_ROLES = {"consumer": ROLE_CONSUMER, "provider": ROLE_PROVIDER, "router": ROLE_ROUTER}


def _parse_address(address: str) -> tuple[str, int]:
    """Parse ``host:port`` or ``zap://host:port`` into ``(host, port)``."""
    addr = address
    if "://" in addr:
        addr = addr.split("://", 1)[1]
    host, _, port = addr.rpartition(":")
    if not host or not port:
        raise ValueError(f"invalid ZAP address: {address!r} (want host:port)")
    return host, int(port)


def _capabilities(info: dict[str, Any]) -> ServerInfo:
    from zap.types import Capabilities, ServerInfo

    caps = info.get("capabilities") or {}
    return ServerInfo(
        name=info.get("name", ""),
        version=info.get("version", ""),
        capabilities=Capabilities(
            tools=caps.get("tools", True),
            resources=caps.get("resources", True),
            prompts=caps.get("prompts", True),
            logging=caps.get("logging", True),
        ),
    )


class Client:
    """Synchronous ZAP RPC client.

    Example:
        >>> with Client("localhost:9999") as client:
        ...     tools = client.list_tools()
        ...     result = client.call_tool("search", {"query": "hello"})
    """

    def __init__(self, address: str):
        self.address = address
        self._host, self._port = _parse_address(address)
        self._rpc: _RpcClient | None = None

    def __enter__(self) -> Client:
        self.connect()
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    @property
    def _conn(self) -> _RpcClient:
        if self._rpc is None:
            raise RuntimeError("client not connected; call connect() first")
        return self._rpc

    def connect(self, name: str = "zap-client", version: str = "0.1.0") -> ServerInfo:
        """Connect and perform the ``init`` handshake; return server info."""
        self._rpc = _RpcClient.connect(self._host, self._port)
        info = self._conn.call(Method.INIT, {"name": name, "version": version})
        return _capabilities(info)

    def close(self) -> None:
        if self._rpc is not None:
            self._rpc.close()
            self._rpc = None

    def list_tools(self) -> list[Tool]:
        rows = self._conn.call(Method.LIST_TOOLS) or []
        return [
            Tool(name=r["name"], description=r.get("description", ""), schema=r.get("schema") or {})
            for r in rows
        ]

    def call_tool(self, name: str, args: dict[str, Any]) -> ToolResult:
        r = self._conn.call(Method.CALL_TOOL, {"name": name, "args": args}) or {}
        return ToolResult(
            id=r.get("id", name),
            content=(r.get("content") or "").encode("utf-8"),
            error=r.get("error", ""),
        )

    def list_resources(self) -> list[Resource]:
        rows = self._conn.call(Method.LIST_RESOURCES) or []
        return [
            Resource(
                uri=r["uri"],
                name=r.get("name", ""),
                description=r.get("description", ""),
                mime_type=r.get("mimeType", "text/plain"),
            )
            for r in rows
        ]

    def read_resource(self, uri: str) -> ResourceContent:
        r = self._conn.call(Method.READ_RESOURCE, {"uri": uri}) or {}
        blob = r.get("blob")
        return ResourceContent(
            uri=r.get("uri", uri),
            mime_type=r.get("mimeType", "text/plain"),
            text=r.get("text"),
            blob=blob.encode("utf-8") if blob is not None else None,
        )

    def list_prompts(self) -> list[Prompt]:
        rows = self._conn.call(Method.LIST_PROMPTS) or []
        return [
            Prompt(
                name=r["name"],
                description=r.get("description", ""),
                arguments=[
                    PromptArgument(
                        name=a["name"],
                        description=a.get("description", ""),
                        required=a.get("required", False),
                    )
                    for a in r.get("arguments", [])
                ],
            )
            for r in rows
        ]

    def get_prompt(self, name: str, args: dict[str, str] | None = None) -> list[PromptMessage]:
        rows = self._conn.call(Method.GET_PROMPT, {"name": name, "args": args or {}}) or []
        return [PromptMessage(role=m["role"], content=m["content"]) for m in rows]

    def log(self, level: str, message: str, data: dict[str, Any] | None = None) -> None:
        self._conn.call(Method.LOG, {"level": level, "message": message, "data": data})


def connect(address: str) -> Client:
    """Create and connect a ZAP client."""
    client = Client(address)
    client.connect()
    return client


# ── Router client — talk to the local zapd daemon over its UDS ─────────────


class ZapClient:
    """Synchronous client for the local ``zapd`` router.

    >>> c = ZapClient.connect(id="consumer:hanzo-mcp/123", role="consumer")
    >>> [p.id for p in c.providers_list(kind="browser")]
    ['browser:chrome/dbc/default']
    >>> c.route(to="browser:chrome/dbc/default", payload=frame.encode_cmd("Target.getTargets", {}))
    b'{"targetInfos": ...}'
    """

    def __init__(self, sock: socket.socket, node_id: str):
        self._sock = sock
        self.node_id = node_id
        self._lock = threading.Lock()

    @classmethod
    def connect(
        cls,
        id: str | None = None,
        role: str = "consumer",
        brand: str = "hanzo",
        caps: Iterable[str] = (),
        path: str | None = None,
        timeout: float = 10.0,
    ) -> ZapClient:
        node_id = id or f"consumer:zap/{os.getpid()}"
        s = socket.socket(socket.AF_UNIX)
        s.settimeout(timeout)
        s.connect(path or frame.socket_path())
        c = cls(s, node_id)
        c.hello(role=role, id=node_id, brand=brand, caps=caps)
        return c

    def hello(
        self,
        role: str | int = "consumer",
        id: str | None = None,
        brand: str = "hanzo",
        caps: Iterable[str] = (),
    ) -> None:
        if id:
            self.node_id = id
        r = _ROLES.get(role, ROLE_CONSUMER) if isinstance(role, str) else role
        self._sock.sendall(
            Frame(HELLO, self.node_id, "", frame.encode_hello(r, brand, list(caps))).encode()
        )
        self._read_until(WELCOME)

    def providers_list(self, kind: str = "", brand: str = "") -> list[Provider]:
        """List providers. ``kind`` filters by id prefix (e.g. ``browser``)."""
        with self._lock:
            payload = frame._put_str(brand) if brand else b""
            self._sock.sendall(Frame(PROVIDERS_LIST, self.node_id, "", payload).encode())
            f = self._read_until(PROVIDERS)
            provs = frame.parse_providers(f.payload)
            return [p for p in provs if not kind or p.id.startswith(kind + ":")]

    def route(self, to: str, payload: bytes, timeout: float = 30.0) -> bytes:
        """Route an opaque payload to ``to`` and return its RESPONSE payload."""
        with self._lock:
            self._sock.settimeout(timeout)
            self._sock.sendall(Frame(ROUTE, self.node_id, to, payload).encode())
            return self._read_until(RESPONSE, frm=to).payload

    def close(self) -> None:
        with contextlib.suppress(OSError):
            self._sock.close()

    def _read_until(self, typ: int, frm: str | None = None) -> Frame:
        for _ in range(100):
            f = Frame.read(self._sock)
            if f.typ == typ and (frm is None or f.frm == frm):
                return f
            if f.typ == ERROR:
                raise RuntimeError(f.payload.decode(errors="replace"))
        raise TimeoutError(f"zap: no frame type {typ}")
