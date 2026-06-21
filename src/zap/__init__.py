"""ZAP — Zero-copy App Proto for Python.

The core is the zero-copy wire codec (:mod:`zap.wire`): a pure-stdlib,
byte-faithful port of the canonical Go runtime (``zap-proto/go``). It is always
importable with no third-party dependency on the import path::

    from zap import Builder, parse

    b = Builder()
    ob = b.start_object(8)
    ob.set_uint32(0, 0xDEADBEEF)
    ob.finish_as_root()
    msg = parse(b.finish())
    assert msg.root().uint32(0) == 0xDEADBEEF

Also pure-stdlib and always available: the router-envelope codec
(:mod:`zap.frame` + :class:`ZapClient`), the browser/agent JSON framing
(:mod:`zap.protocol`), W3C DID identity (:mod:`zap.identity`), and agent
consensus (:mod:`zap.consensus`).

Two areas need an extra and are imported lazily — accessing the name raises a
clear ImportError (never a silent stub) if the extra is missing:

* :mod:`zap.crypto` (``[crypto]``) — real ML-KEM-768 / ML-DSA-65 / X25519;
* :class:`ZAP` and the HTTP :class:`Client` (``[app]``) — pydantic + httpx.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

# ── Core: zero-copy wire codec (pure stdlib, always importable) ─────────────
# `cap` (the capability runtime) is importable here with no third-party dep —
# its crypto backends are guarded and fail loudly only when a sign/verify call
# actually needs them (the wire/canonical/CapID paths are pure stdlib).
from zap import cap, frame, protocol, wire

# ZapClient (router UDS client) is pure-stdlib; the HTTP Client is not, so it
# is resolved lazily below.
from zap.client import ZapClient
from zap.consensus import AgentConsensus, Query, Response, Vote
from zap.frame import Frame
from zap.identity import DID, DIDMethod
from zap.pipeline import (
    NO_TARGET,
    STATUS_BAD_REQUEST,
    STATUS_OK,
    Call,
    Pipeliner,
    Promise,
    Session,
    build_request,
    build_response,
    parse_request,
    parse_response,
)
from zap.types import (
    Capabilities,
    ClientInfo,
    Prompt,
    PromptArgument,
    PromptMessage,
    Resource,
    ResourceContent,
    ServerInfo,
    Tool,
    ToolResult,
)
from zap.wire import (
    DEFAULT_PORT,
    HEADER_SIZE,
    MAGIC,
    VERSION,
    VERSION1,
    VERSION2,
    Builder,
    List,
    ListBuilder,
    Message,
    Object,
    ObjectBuilder,
    ZapError,
    parse,
)

if TYPE_CHECKING:  # for type checkers / IDEs only — not imported at runtime
    from zap.app import ZAP
    from zap.client import Client

__version__ = "1.4.0"

# Names served lazily by __getattr__ -> (module, attribute). Importing these
# pulls the [app] extra (pydantic/httpx); a missing extra raises ImportError.
_LAZY: dict[str, tuple[str, str]] = {
    "ZAP": ("zap.app", "ZAP"),
    "Client": ("zap.client", "Client"),
}


def __getattr__(name: str) -> Any:
    target = _LAZY.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    mod = importlib.import_module(target[0])
    return getattr(mod, target[1])


def __dir__() -> list[str]:
    return sorted(list(globals()) + list(_LAZY))


__all__ = [
    # Wire codec (the product)
    "wire",
    "parse",
    "Message",
    "Object",
    "List",
    "Builder",
    "ObjectBuilder",
    "ListBuilder",
    "ZapError",
    "MAGIC",
    "VERSION",
    "VERSION1",
    "VERSION2",
    "HEADER_SIZE",
    "DEFAULT_PORT",
    # Capability runtime (signed, attenuable authority tokens)
    "cap",
    # Promise pipelining (the canonical ZAP model — peer of Go/TS Session+Pipeliner)
    "Session",
    "Pipeliner",
    "Promise",
    "Call",
    "build_request",
    "build_response",
    "parse_request",
    "parse_response",
    "NO_TARGET",
    "STATUS_OK",
    "STATUS_BAD_REQUEST",
    # Router / framing
    "frame",
    "protocol",
    "Frame",
    "ZapClient",
    # App (lazy — needs [app] extra)
    "ZAP",
    "Client",
    # Types
    "Tool",
    "ToolResult",
    "Resource",
    "ResourceContent",
    "Prompt",
    "PromptArgument",
    "PromptMessage",
    "ServerInfo",
    "ClientInfo",
    "Capabilities",
    # Identity
    "DID",
    "DIDMethod",
    # Consensus
    "AgentConsensus",
    "Query",
    "Response",
    "Vote",
]
