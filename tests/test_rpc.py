"""ZAP RPC — real client <-> server over TCP, dispatching method ordinals.

These tests stand a real :class:`zap.rpc.Server` on a background thread and drive
it with a real :class:`zap.rpc.Client`; nothing is mocked.
"""

import threading

import pytest

from zap.rpc import Client, Method, RpcError, Server


def _serve(server: Server) -> threading.Thread:
    server.bind()
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return t


def test_rpc_call_dispatches_to_handler():
    server = Server()
    server.handle(Method.CALL_TOOL, lambda p: {"sum": p["a"] + p["b"]})
    _serve(server)
    try:
        client = Client.connect("127.0.0.1", server.port)
        assert client.call(Method.CALL_TOOL, {"a": 3, "b": 4}) == {"sum": 7}
    finally:
        client.close()
        server.close()


def test_rpc_multiple_sequential_calls():
    server = Server()
    server.handle(Method.LIST_TOOLS, lambda _p: ["a", "b"])
    server.handle(Method.INIT, lambda p: {"echo": p})
    _serve(server)
    try:
        client = Client.connect("127.0.0.1", server.port)
        assert client.call(Method.LIST_TOOLS) == ["a", "b"]
        assert client.call(Method.INIT, {"x": 1}) == {"echo": {"x": 1}}
        assert client.call(Method.LIST_TOOLS) == ["a", "b"]
    finally:
        client.close()
        server.close()


def test_rpc_handler_error_propagates():
    server = Server()

    def boom(_p):
        raise ValueError("kaboom")

    server.handle(Method.CALL_TOOL, boom)
    _serve(server)
    try:
        client = Client.connect("127.0.0.1", server.port)
        with pytest.raises(RpcError, match="kaboom"):
            client.call(Method.CALL_TOOL, {})
    finally:
        client.close()
        server.close()


def test_rpc_unknown_method():
    server = Server()
    _serve(server)
    try:
        client = Client.connect("127.0.0.1", server.port)
        with pytest.raises(RpcError, match="unknown method"):
            client.call(Method.LOG, {})
    finally:
        client.close()
        server.close()
