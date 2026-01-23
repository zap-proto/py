"""Tests for ZAP application."""

import pytest
from zap import ZAP, PromptMessage


def test_create_app():
    app = ZAP("test-app", version="1.0.0")
    assert app.name == "test-app"
    assert app.version == "1.0.0"


def test_register_tool():
    app = ZAP("test")

    @app.tool
    def add(a: int, b: int) -> int:
        """Add two numbers"""
        return a + b

    tools = app.list_tools()
    assert len(tools) == 1
    assert tools[0].name == "add"
    assert tools[0].description == "Add two numbers"


def test_register_tool_with_options():
    app = ZAP("test")

    @app.tool(name="custom_name", description="Custom description")
    def my_func(x: str) -> str:
        return x

    tools = app.list_tools()
    assert tools[0].name == "custom_name"
    assert tools[0].description == "Custom description"


@pytest.mark.asyncio
async def test_call_tool():
    app = ZAP("test")

    @app.tool
    def multiply(a: int, b: int) -> int:
        return a * b

    result = await app.call_tool("multiply", {"a": 3, "b": 4})
    assert result.content == b"12"
    assert result.error == ""


@pytest.mark.asyncio
async def test_call_tool_not_found():
    app = ZAP("test")
    result = await app.call_tool("nonexistent", {})
    assert "not found" in result.error.lower()


def test_register_resource():
    app = ZAP("test")

    @app.resource("test://{id}")
    def get_test(id: str) -> str:
        return f"Test {id}"

    resources = app.list_resources()
    assert len(resources) == 1
    assert resources[0].uri == "test://{id}"


@pytest.mark.asyncio
async def test_read_resource():
    app = ZAP("test")

    @app.resource("test://{id}")
    def get_test(id: str) -> str:
        return f"Content for {id}"

    content = await app.read_resource("test://123")
    assert content.text == "Content for 123"


def test_register_prompt():
    app = ZAP("test")

    @app.prompt
    def greeting(name: str) -> list[PromptMessage]:
        return [PromptMessage(role="assistant", content=f"Hello, {name}!")]

    prompts = app.list_prompts()
    assert len(prompts) == 1
    assert prompts[0].name == "greeting"


@pytest.mark.asyncio
async def test_get_prompt():
    app = ZAP("test")

    @app.prompt
    def greeting(name: str) -> list[PromptMessage]:
        return [PromptMessage(role="assistant", content=f"Hello, {name}!")]

    messages = await app.get_prompt("greeting", {"name": "World"})
    assert len(messages) == 1
    assert messages[0].content == "Hello, World!"


def test_server_info():
    app = ZAP("test-server", version="2.0.0")
    info = app.info
    assert info.name == "test-server"
    assert info.version == "2.0.0"
    assert info.capabilities.tools is True
