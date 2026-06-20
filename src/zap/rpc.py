"""ZAP RPC — a real request/response transport over the wire.

This is the concrete RPC layer the :class:`zap.app.ZAP` server and the
:class:`zap.client.Client` use. It is NOT a mock or a sleep loop: a server binds
a TCP socket, reads length-prefixed request frames, dispatches each to the
handler registered for its method ordinal, and writes back a response frame; the
client connects, sends a request frame, and blocks for the correlated response.

Method ordinals are exactly the ``Zap`` interface declared in ``zap.zap``
(``init @0`` .. ``log @8``) — :class:`Method`.

Frame layout (one frame per request and per response)::

    [ ZAP_MAGIC (4) ][ msg_type:u8 ][ length:u32 BE ][ JSON body ]

reusing :mod:`zap.protocol`'s magic-framed envelope. The JSON body is::

    request : {"id": int, "method": int, "params": <json>}
    response: {"id": int, "ok": true, "result": <json>}
            | {"id": int, "ok": false, "error": str}

``id`` correlates a response to its request. JSON is the body codec because the
RPC method parameters here are already JSON-shaped (tool args, resource URIs);
the zero-copy struct codec (:mod:`zap.wire`) is the data-plane primitive for
callers who need it and is exercised independently.

Pure stdlib — ``socket`` + ``json``. No third-party dependency.
"""

from __future__ import annotations

import contextlib
import json
import socket
import struct
import threading
from collections.abc import Callable
from enum import IntEnum
from typing import Any

from zap.protocol import (
    HEADER_SIZE,
    MAX_MESSAGE_SIZE,
    MSG_REQUEST,
    MSG_RESPONSE,
    ZAP_MAGIC,
)

#: Handler signature: receives the decoded params, returns a JSON-able result.
Handler = Callable[[Any], Any]


class Method(IntEnum):
    """``Zap`` interface method ordinals (verbatim from ``zap.zap``)."""

    INIT = 0
    LIST_TOOLS = 1
    CALL_TOOL = 2
    LIST_RESOURCES = 3
    READ_RESOURCE = 4
    SUBSCRIBE = 5
    LIST_PROMPTS = 6
    GET_PROMPT = 7
    LOG = 8


class RpcError(Exception):
    """A remote handler raised, or the peer returned an error response."""


# ── Framing ────────────────────────────────────────────────────────────────


def _encode(msg_type: int, body: dict[str, Any]) -> bytes:
    payload = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(payload) > MAX_MESSAGE_SIZE:
        raise RpcError(f"zap rpc: body exceeds max size ({len(payload)})")
    return ZAP_MAGIC + struct.pack("!BL", msg_type & 0xFF, len(payload)) + payload


def _recvn(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("zap rpc: connection closed")
        buf += chunk
    return bytes(buf)


def _read_frame(sock: socket.socket) -> tuple[int, dict[str, Any]]:
    head = _recvn(sock, HEADER_SIZE)
    if head[:4] != ZAP_MAGIC:
        raise RpcError("zap rpc: bad magic")
    msg_type = head[4]
    (length,) = struct.unpack("!L", head[5:9])
    if length > MAX_MESSAGE_SIZE:
        raise RpcError(f"zap rpc: frame too large ({length})")
    body = _recvn(sock, length) if length else b""
    return msg_type, json.loads(body.decode("utf-8")) if body else {}


# ── Server ─────────────────────────────────────────────────────────────────


class Server:
    """A blocking, threaded ZAP RPC server.

    Register a handler per :class:`Method` with :meth:`handle`, then
    :meth:`serve_forever` (or :meth:`serve_one` for a single connection, which
    the tests use). Each accepted connection is served on its own thread and may
    carry many sequential requests.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 0):
        self.host = host
        self.port = port
        self._handlers: dict[int, Handler] = {}
        self._sock: socket.socket | None = None
        self._serving = False
        self._threads: list[threading.Thread] = []

    def handle(self, method: Method, fn: Handler) -> None:
        """Register ``fn`` as the handler for ``method``."""
        self._handlers[int(method)] = fn

    def bind(self) -> int:
        """Bind and listen; return the bound port (resolves port 0)."""
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((self.host, self.port))
        s.listen(64)
        self.port = s.getsockname()[1]
        self._sock = s
        return self.port

    def _dispatch(self, req: dict[str, Any]) -> dict[str, Any]:
        rid = req.get("id", 0)
        method = req.get("method")
        handler = self._handlers.get(method) if isinstance(method, int) else None
        if handler is None:
            return {"id": rid, "ok": False, "error": f"unknown method ordinal: {method}"}
        try:
            result = handler(req.get("params"))
        except Exception as e:  # surface the handler error to the caller
            return {"id": rid, "ok": False, "error": str(e)}
        return {"id": rid, "ok": True, "result": result}

    def _serve_conn(self, conn: socket.socket) -> None:
        with conn:
            while True:
                try:
                    msg_type, req = _read_frame(conn)
                except (ConnectionError, RpcError, json.JSONDecodeError):
                    return
                if msg_type != MSG_REQUEST:
                    continue
                conn.sendall(_encode(MSG_RESPONSE, self._dispatch(req)))

    def serve_one(self) -> None:
        """Accept and fully serve exactly one connection (blocking)."""
        if self._sock is None:
            self.bind()
        assert self._sock is not None
        conn, _ = self._sock.accept()
        self._serve_conn(conn)

    def serve_forever(self) -> None:
        """Accept connections until :meth:`close`, one thread per connection."""
        if self._sock is None:
            self.bind()
        assert self._sock is not None
        self._serving = True
        while self._serving:
            try:
                conn, _ = self._sock.accept()
            except OSError:
                break
            t = threading.Thread(target=self._serve_conn, args=(conn,), daemon=True)
            t.start()
            self._threads.append(t)

    def close(self) -> None:
        """Stop serving and close the listening socket."""
        self._serving = False
        if self._sock is not None:
            with contextlib.suppress(OSError):
                self._sock.close()
            self._sock = None


# ── Client ─────────────────────────────────────────────────────────────────


class Client:
    """A blocking ZAP RPC client over TCP.

    >>> c = Client.connect("127.0.0.1", port)
    >>> c.call(Method.CALL_TOOL, {"name": "add", "args": {"a": 1, "b": 2}})
    """

    def __init__(self, sock: socket.socket):
        self._sock = sock
        self._next_id = 1
        self._lock = threading.Lock()

    @classmethod
    def connect(cls, host: str, port: int, timeout: float = 10.0) -> Client:
        s = socket.create_connection((host, port), timeout=timeout)
        return cls(s)

    def call(self, method: Method, params: Any = None) -> Any:
        """Send a request for ``method`` and return the decoded result.

        Raises :class:`RpcError` if the peer returns an error response.
        """
        with self._lock:
            rid = self._next_id
            self._next_id += 1
            self._sock.sendall(
                _encode(MSG_REQUEST, {"id": rid, "method": int(method), "params": params})
            )
            msg_type, resp = _read_frame(self._sock)
        if msg_type != MSG_RESPONSE:
            raise RpcError(f"zap rpc: expected response, got msg_type {msg_type}")
        if resp.get("id") != rid:
            raise RpcError(f"zap rpc: response id {resp.get('id')} != request id {rid}")
        if not resp.get("ok"):
            raise RpcError(resp.get("error", "unknown error"))
        return resp.get("result")

    def close(self) -> None:
        with contextlib.suppress(OSError):
            self._sock.close()
