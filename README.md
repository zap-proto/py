# ZAP Python

> **Docs:** [ZAP Python SDK](https://zap-proto.dev/docs/sdks/python) · part of the [ZAP Protocol](https://zap-proto.io)

`zap-proto` is the Python implementation of **ZAP** (Zero-Copy App Proto): a
zero-copy binary wire format plus a small RPC layer for AI-agent communication.

The core — the wire codec, router envelope, JSON framing, RPC client/server,
identity, and consensus — is **pure standard library**. `import zap` pulls no
third-party dependency.

## Installation

```bash
pip install zap-proto
# or
uv add zap-proto
```

Optional extras:

```bash
pip install "zap-proto[crypto]"  # real ML-KEM-768 / ML-DSA-65 / X25519
pip install "zap-proto[app]"     # the FastMCP-style decorator app (pydantic)
```

## Wire format (the core)

The zero-copy codec is byte-for-byte compatible with the canonical Go runtime
(`zap-proto/go`) — the same 16-byte `ZAP\x00` header, the same fixed-offset
struct layout. A buffer this library writes is read by Go and vice versa.

```python
from zap import Builder, parse

# Build a message: field @0 uint32, @8 text, @16 bytes.
b = Builder()
obj = b.start_object(24)
obj.set_uint32(0, 0xDEADBEEF)
obj.set_text(8, "zap")
obj.set_bytes(16, b"\x01\x02\x03\x04")
obj.finish_as_root()
buf = b.finish()

# Read it back with zero copy.
root = parse(buf).root()
assert root.uint32(0) == 0xDEADBEEF
assert root.text(8) == "zap"
assert root.bytes(16) == b"\x01\x02\x03\x04"
```

Lists (flat fixed-stride and variable-element) and nested objects are supported;
the reader rejects out-of-bounds and backward pointers that would alias the wire
header, and clamps list lengths — so an adversarial buffer that Go rejects is
rejected here too.

## RPC

A real request/response transport over TCP, dispatching the `Zap` interface
method ordinals declared in `zap.zap`.

### Server (decorator app — needs `[app]`)

```python
from zap import ZAP, PromptMessage

app = ZAP("my-agent", version="1.0.0")

@app.tool
def search(query: str, limit: int = 10) -> list[dict]:
    """Search for content in the knowledge base"""
    return [{"title": f"Result for {query}", "score": 0.95}]

@app.resource("file://{path}")
def read_file(path: str) -> str:
    """Read a file from disk"""
    return open(path).read()

@app.prompt
def greeting(name: str) -> list[PromptMessage]:
    """Generate a personalized greeting"""
    return [PromptMessage(role="assistant", content=f"Hello, {name}!")]

if __name__ == "__main__":
    app.run(port=9999)  # serves real ZAP RPC
```

### Client

```python
from zap import Client

with Client("localhost:9999") as client:
    info = client.connect()
    tools = client.list_tools()
    result = client.call_tool("search", {"query": "hello world"})
    print(result.content)            # bytes
    content = client.read_resource("file:///tmp/test.txt")
    print(content.text)
```

## Router client

`ZapClient` talks to the local `zapd` router over its Unix domain socket
(byte-compatible with `zap-proto/zapd`'s frame codec). Used by
`hanzo-tools-browser`'s `zapd_consumer`.

```python
from zap import ZapClient, frame

c = ZapClient.connect(id="consumer:hanzo-mcp/123", role="consumer")
providers = c.providers_list(kind="browser")
reply = c.route(to=providers[0].id, payload=frame.encode_cmd("Target.getTargets", {}))
```

## Post-quantum cryptography (needs `[crypto]`)

Real ML-KEM-768 (FIPS 203) + ML-DSA-65 (FIPS 204) via `pqcrypto`, classical
X25519 via `cryptography`, mixed with HKDF-SHA256. There is no silent fallback:
if a backend is missing, every operation raises `CryptoError`.

```python
from zap import HybridKeyExchange

alice = HybridKeyExchange.generate()
bob = HybridKeyExchange.generate()

a_x_pub, a_k_pub = alice.initiate()
b_x_pub, ciphertext, bob_secret = bob.respond(a_x_pub, a_k_pub)
alice_secret = alice.finalize(b_x_pub, ciphertext)

assert alice_secret == bob_secret  # both sides agree
```

## Agent consensus

```python
from zap import AgentConsensus, Query, Response, DID, DIDMethod

consensus = AgentConsensus()
agent = DID(method=DIDMethod.KEY, id="z6MkAgent...")

query = Query.create("What is the capital of France?", agent)
consensus.submit_query(query)
```

## Related packages

- [zap-proto/go](https://github.com/zap-proto/go) — canonical Go runtime
- [zap-proto/js](https://github.com/zap-proto/js) — JavaScript/TypeScript
- [zap-proto/spec](https://github.com/zap-proto/spec) — schema + reference

## License

MIT
