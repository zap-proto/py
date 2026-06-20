"""
ZAP Application - FastMCP-inspired server framework.

Provides decorator-based registration for tools, resources, and prompts.
"""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ParamSpec, TypeVar

from pydantic import BaseModel, create_model
from pydantic.fields import FieldInfo

from zap.types import (
    Capabilities,
    Prompt,
    PromptArgument,
    PromptMessage,
    Resource,
    ResourceContent,
    ServerInfo,
    Tool,
    ToolResult,
)

if TYPE_CHECKING:
    from zap.rpc import Server

P = ParamSpec("P")
R = TypeVar("R")


def _get_schema_from_func(func: Callable[..., Any]) -> dict[str, Any]:
    """Generate JSON Schema from function signature using Pydantic."""
    sig = inspect.signature(func)
    fields: dict[str, tuple[type, FieldInfo | Any]] = {}

    for name, param in sig.parameters.items():
        if name in ("self", "cls"):
            continue

        annotation = param.annotation
        if annotation is inspect.Parameter.empty:
            annotation = Any

        if param.default is inspect.Parameter.empty:
            fields[name] = (annotation, ...)
        else:
            fields[name] = (annotation, param.default)

    model = create_model(f"{func.__name__}_args", **fields)  # type: ignore[call-overload]
    schema: dict[str, Any] = model.model_json_schema()
    return schema


@dataclass
class RegisteredTool:
    """A registered tool with its handler function."""

    name: str
    description: str
    schema: dict[str, Any]
    handler: Callable[..., Any]
    annotations: dict[str, str] = field(default_factory=dict)

    def to_tool(self) -> Tool:
        return Tool(
            name=self.name,
            description=self.description,
            schema=self.schema,
            annotations=self.annotations,
        )


@dataclass
class RegisteredResource:
    """A registered resource with its provider function."""

    uri: str
    name: str
    description: str
    mime_type: str
    provider: Callable[..., Any]
    annotations: dict[str, str] = field(default_factory=dict)

    def to_resource(self) -> Resource:
        return Resource(
            uri=self.uri,
            name=self.name,
            description=self.description,
            mime_type=self.mime_type,
            annotations=self.annotations,
        )


@dataclass
class RegisteredPrompt:
    """A registered prompt with its generator function."""

    name: str
    description: str
    arguments: list[PromptArgument]
    generator: Callable[..., Any]

    def to_prompt(self) -> Prompt:
        return Prompt(
            name=self.name,
            description=self.description,
            arguments=self.arguments,
        )


class ZAP:
    """
    ZAP Application Server.

    FastMCP-inspired decorator-based API for building ZAP servers.

    Example:
        >>> app = ZAP("my-agent", version="1.0.0")
        >>>
        >>> @app.tool
        >>> def add(a: int, b: int) -> int:
        ...     '''Add two numbers together'''
        ...     return a + b
        >>>
        >>> @app.resource("file://{path}")
        >>> def read_file(path: str) -> str:
        ...     '''Read a file from disk'''
        ...     return open(path).read()
        >>>
        >>> @app.prompt
        >>> def greeting(name: str) -> list[PromptMessage]:
        ...     '''Generate a greeting'''
        ...     return [PromptMessage(role="assistant", content=f"Hello, {name}!")]
        >>>
        >>> app.run(port=9999)
    """

    def __init__(
        self,
        name: str,
        version: str = "0.1.0",
        *,
        enable_tools: bool = True,
        enable_resources: bool = True,
        enable_prompts: bool = True,
        enable_logging: bool = True,
    ):
        self.name = name
        self.version = version
        self._capabilities = Capabilities(
            tools=enable_tools,
            resources=enable_resources,
            prompts=enable_prompts,
            logging=enable_logging,
        )
        self._tools: dict[str, RegisteredTool] = {}
        self._resources: dict[str, RegisteredResource] = {}
        self._prompts: dict[str, RegisteredPrompt] = {}
        self._running = False
        self._server: Server | None = None

    @property
    def info(self) -> ServerInfo:
        """Get server information."""
        return ServerInfo(
            name=self.name,
            version=self.version,
            capabilities=self._capabilities,
        )

    # ========== Tool Registration ==========

    def tool(
        self,
        func: Callable[P, R] | None = None,
        *,
        name: str | None = None,
        description: str | None = None,
        annotations: dict[str, str] | None = None,
    ) -> Callable[P, R] | Callable[[Callable[P, R]], Callable[P, R]]:
        """
        Register a function as a tool.

        Can be used as a decorator with or without arguments:

            @app.tool
            def search(query: str) -> list[str]:
                ...

            @app.tool(name="custom_name", description="Custom description")
            def search(query: str) -> list[str]:
                ...
        """

        def decorator(fn: Callable[P, R]) -> Callable[P, R]:
            tool_name = name or fn.__name__
            tool_desc = description or fn.__doc__ or ""
            schema = _get_schema_from_func(fn)

            self._tools[tool_name] = RegisteredTool(
                name=tool_name,
                description=tool_desc.strip(),
                schema=schema,
                handler=fn,
                annotations=annotations or {},
            )
            return fn

        if func is not None:
            return decorator(func)
        return decorator

    async def call_tool(self, name: str, args: dict[str, Any]) -> ToolResult:
        """Call a registered tool by name."""
        if name not in self._tools:
            return ToolResult(id="", error=f"Tool not found: {name}")

        tool = self._tools[name]
        try:
            result = tool.handler(**args)
            if asyncio.iscoroutine(result):
                result = await result

            if isinstance(result, BaseModel):
                content = result.model_dump_json().encode()
            elif isinstance(result, (dict, list)):
                content = json.dumps(result).encode()
            elif isinstance(result, bytes):
                content = result
            else:
                content = str(result).encode()

            return ToolResult(id=name, content=content)
        except Exception as e:
            return ToolResult(id=name, error=str(e))

    def list_tools(self) -> list[Tool]:
        """List all registered tools."""
        return [t.to_tool() for t in self._tools.values()]

    # ========== Resource Registration ==========

    def resource(
        self,
        uri_template: str,
        *,
        name: str | None = None,
        description: str | None = None,
        mime_type: str = "text/plain",
        annotations: dict[str, str] | None = None,
    ) -> Callable[[Callable[P, R]], Callable[P, R]]:
        """
        Register a function as a resource provider.

        Example:
            @app.resource("file://{path}")
            def read_file(path: str) -> str:
                return open(path).read()
        """

        def decorator(fn: Callable[P, R]) -> Callable[P, R]:
            resource_name = name or fn.__name__
            resource_desc = description or fn.__doc__ or ""

            self._resources[uri_template] = RegisteredResource(
                uri=uri_template,
                name=resource_name,
                description=resource_desc.strip(),
                mime_type=mime_type,
                provider=fn,
                annotations=annotations or {},
            )
            return fn

        return decorator

    async def read_resource(self, uri: str) -> ResourceContent:
        """Read a resource by URI."""
        # Find matching resource template
        for template, resource in self._resources.items():
            params = self._match_uri_template(template, uri)
            if params is not None:
                result = resource.provider(**params)
                if asyncio.iscoroutine(result):
                    result = await result

                if isinstance(result, bytes):
                    return ResourceContent(
                        uri=uri,
                        mime_type=resource.mime_type,
                        blob=result,
                    )
                return ResourceContent(
                    uri=uri,
                    mime_type=resource.mime_type,
                    text=str(result),
                )

        raise ValueError(f"Resource not found: {uri}")

    def list_resources(self) -> list[Resource]:
        """List all registered resources."""
        return [r.to_resource() for r in self._resources.values()]

    @staticmethod
    def _match_uri_template(template: str, uri: str) -> dict[str, str] | None:
        """Match a URI against a template and extract ``{param}`` segments.

        The literal parts of the template are regex-escaped, so a ``.`` in
        ``file://a.b`` matches a literal dot, not any character — no
        over-matching or ReDoS surface from template text.
        """
        import re

        # Split on {param} placeholders, escape the literal pieces, and replace
        # each placeholder with a named capture group.
        parts = re.split(r"\{(\w+)\}", template)
        pattern = "".join(
            f"(?P<{piece}>[^/]+)" if i % 2 else re.escape(piece) for i, piece in enumerate(parts)
        )
        match = re.fullmatch(pattern, uri)
        if match:
            return match.groupdict()
        return None

    # ========== Prompt Registration ==========

    def prompt(
        self,
        func: Callable[P, R] | None = None,
        *,
        name: str | None = None,
        description: str | None = None,
    ) -> Callable[P, R] | Callable[[Callable[P, R]], Callable[P, R]]:
        """
        Register a function as a prompt generator.

        Example:
            @app.prompt
            def greeting(name: str) -> list[PromptMessage]:
                return [PromptMessage(role="assistant", content=f"Hello, {name}!")]
        """

        def decorator(fn: Callable[P, R]) -> Callable[P, R]:
            prompt_name = name or fn.__name__
            prompt_desc = description or fn.__doc__ or ""

            # Extract arguments from function signature
            sig = inspect.signature(fn)
            arguments = []
            for param_name, param in sig.parameters.items():
                if param_name in ("self", "cls"):
                    continue
                arguments.append(
                    PromptArgument(
                        name=param_name,
                        description="",
                        required=param.default is inspect.Parameter.empty,
                    )
                )

            self._prompts[prompt_name] = RegisteredPrompt(
                name=prompt_name,
                description=prompt_desc.strip(),
                arguments=arguments,
                generator=fn,
            )
            return fn

        if func is not None:
            return decorator(func)
        return decorator

    async def get_prompt(self, name: str, args: dict[str, str]) -> list[PromptMessage]:
        """Get a prompt by name with arguments."""
        if name not in self._prompts:
            raise ValueError(f"Prompt not found: {name}")

        prompt = self._prompts[name]
        result = prompt.generator(**args)
        if asyncio.iscoroutine(result):
            result = await result
        messages: list[PromptMessage] = result
        return messages

    def list_prompts(self) -> list[Prompt]:
        """List all registered prompts."""
        return [p.to_prompt() for p in self._prompts.values()]

    # ========== Server Lifecycle ==========

    def build_rpc_server(self, host: str = "0.0.0.0", port: int = 9999) -> Server:
        """Build a :class:`zap.rpc.Server` wired to this app's registrations.

        Each :class:`~zap.rpc.Method` ordinal is bound to a handler that calls
        the corresponding registry. Params and results are JSON values — the
        same shapes the decorator API already produces. Returned unbound (call
        :meth:`~zap.rpc.Server.bind` / ``serve_forever``) so callers and tests
        control the lifecycle.
        """
        from zap.rpc import Method, Server

        server = Server(host=host, port=port)
        server.handle(Method.INIT, lambda _p: self._rpc_info())
        server.handle(Method.LIST_TOOLS, lambda _p: [self._tool_json(t) for t in self.list_tools()])
        server.handle(Method.CALL_TOOL, self._rpc_call_tool)
        server.handle(
            Method.LIST_RESOURCES,
            lambda _p: [self._resource_json(r) for r in self.list_resources()],
        )
        server.handle(Method.READ_RESOURCE, self._rpc_read_resource)
        server.handle(
            Method.LIST_PROMPTS, lambda _p: [self._prompt_json(p) for p in self.list_prompts()]
        )
        server.handle(Method.GET_PROMPT, self._rpc_get_prompt)
        server.handle(Method.LOG, lambda _p: None)
        return server

    def _rpc_info(self) -> dict[str, Any]:
        info = self.info
        return {
            "name": info.name,
            "version": info.version,
            "capabilities": {
                "tools": info.capabilities.tools,
                "resources": info.capabilities.resources,
                "prompts": info.capabilities.prompts,
                "logging": info.capabilities.logging,
            },
        }

    @staticmethod
    def _tool_json(tool: Tool) -> dict[str, Any]:
        return {"name": tool.name, "description": tool.description, "schema": tool.schema}

    @staticmethod
    def _resource_json(resource: Resource) -> dict[str, Any]:
        return {
            "uri": resource.uri,
            "name": resource.name,
            "description": resource.description,
            "mimeType": resource.mime_type,
        }

    @staticmethod
    def _prompt_json(prompt: Prompt) -> dict[str, Any]:
        return {
            "name": prompt.name,
            "description": prompt.description,
            "arguments": [
                {"name": a.name, "description": a.description, "required": a.required}
                for a in prompt.arguments
            ],
        }

    def _rpc_call_tool(self, params: Any) -> dict[str, Any]:
        params = params or {}
        result = _run_sync(self.call_tool(params.get("name", ""), params.get("args") or {}))
        return {
            "id": result.id,
            "content": result.content.decode("utf-8", "replace"),
            "error": result.error,
        }

    def _rpc_read_resource(self, params: Any) -> dict[str, Any]:
        params = params or {}
        content = _run_sync(self.read_resource(params.get("uri", "")))
        return {
            "uri": content.uri,
            "mimeType": content.mime_type,
            "text": content.text,
            "blob": content.blob.decode("utf-8", "replace") if content.blob else None,
        }

    def _rpc_get_prompt(self, params: Any) -> list[dict[str, Any]]:
        params = params or {}
        messages = _run_sync(self.get_prompt(params.get("name", ""), params.get("args") or {}))
        return [{"role": m.role, "content": m.content} for m in messages]

    def run(
        self,
        host: str = "0.0.0.0",
        port: int = 9999,
        *,
        transport: str = "tcp",
    ) -> None:
        """Run the ZAP RPC server until interrupted.

        Args:
            host: Host to bind to (default: 0.0.0.0)
            port: Port to listen on (default: 9999)
            transport: Transport type (only ``tcp`` is implemented)
        """
        if transport != "tcp":
            raise ValueError(f"unsupported transport: {transport!r} (only 'tcp')")
        server = self.build_rpc_server(host=host, port=port)
        bound = server.bind()
        self._server = server
        self._running = True
        print(f"ZAP server '{self.name}' v{self.version} listening on tcp://{host}:{bound}")
        print(
            f"  tools={len(self._tools)} resources={len(self._resources)} "
            f"prompts={len(self._prompts)}"
        )
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    def stop(self) -> None:
        """Stop the running server."""
        self._running = False
        server = getattr(self, "_server", None)
        if server is not None:
            server.close()
            self._server = None


def _run_sync(coro: Any) -> Any:
    """Run a coroutine to completion from synchronous RPC-handler context."""
    if not asyncio.iscoroutine(coro):
        return coro
    return asyncio.run(coro)
