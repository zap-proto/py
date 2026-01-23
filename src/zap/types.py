"""ZAP Protocol Types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Tool:
    """Tool definition."""

    name: str
    description: str
    schema: dict[str, Any] = field(default_factory=dict)
    annotations: dict[str, str] = field(default_factory=dict)


@dataclass
class ToolResult:
    """Result of a tool call."""

    id: str
    content: bytes = b""
    error: str = ""
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass
class Resource:
    """Resource definition."""

    uri: str
    name: str
    description: str = ""
    mime_type: str = "text/plain"
    annotations: dict[str, str] = field(default_factory=dict)


@dataclass
class ResourceContent:
    """Resource content."""

    uri: str
    mime_type: str
    text: str | None = None
    blob: bytes | None = None


@dataclass
class PromptArgument:
    """Prompt argument definition."""

    name: str
    description: str = ""
    required: bool = False


@dataclass
class Prompt:
    """Prompt definition."""

    name: str
    description: str = ""
    arguments: list[PromptArgument] = field(default_factory=list)


@dataclass
class PromptMessage:
    """Message in a prompt."""

    role: str  # "user", "assistant", "system"
    content: str


@dataclass
class Capabilities:
    """Server capabilities."""

    tools: bool = True
    resources: bool = True
    prompts: bool = True
    logging: bool = True


@dataclass
class ServerInfo:
    """Server information."""

    name: str
    version: str
    capabilities: Capabilities = field(default_factory=Capabilities)


@dataclass
class ClientInfo:
    """Client information."""

    name: str
    version: str
