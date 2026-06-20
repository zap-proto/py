"""End-to-end: a real ZAP app served over real RPC, driven by the real Client.

Proves the decorator-registered tools/resources/prompts are reachable across an
actual TCP socket through the method-ordinal dispatch — no mocks, no sleep loop.
"""

import threading

import pytest

pytest.importorskip("pydantic")

from zap import ZAP  # noqa: E402  (after importorskip)
from zap.client import Client  # noqa: E402
from zap.types import PromptMessage  # noqa: E402


def _make_app() -> ZAP:
    app = ZAP("e2e-agent", version="9.9.9")

    @app.tool
    def add(a: int, b: int) -> int:
        """Add two numbers"""
        return a + b

    @app.resource("mem://{key}")
    def read_mem(key: str) -> str:
        return f"value-of-{key}"

    @app.prompt
    def greet(name: str) -> list[PromptMessage]:
        return [PromptMessage(role="assistant", content=f"Hi {name}")]

    return app


def test_app_served_over_rpc():
    app = _make_app()
    server = app.build_rpc_server(host="127.0.0.1", port=0)
    server.bind()
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        with Client(f"127.0.0.1:{server.port}") as client:
            info = client.connect()
            assert info.name == "e2e-agent"
            assert info.version == "9.9.9"

            tools = client.list_tools()
            assert [t.name for t in tools] == ["add"]

            result = client.call_tool("add", {"a": 5, "b": 6})
            assert result.content == b"11"
            assert result.error == ""

            content = client.read_resource("mem://k1")
            assert content.text == "value-of-k1"

            messages = client.get_prompt("greet", {"name": "Ada"})
            assert messages[0].content == "Hi Ada"
    finally:
        server.close()
