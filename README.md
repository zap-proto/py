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

## Schemas

A `.zap` schema is whitespace-significant — indentation, no braces — and this
library reads it natively and generates the bindings:

```zap
package addressbook

struct Person
  id u64
  name text
  email text
  tags list<Tag>

interface Directory
  find(req: Person) returns (resp: Person)
```

```console
$ python -m zap.schema addressbook.zap     # writes addressbook_zap.py
```

```python
from addressbook_zap import Person

buf = Person.build(id=7, name="Ada", email="ada@example.com")
p = Person.wrap(buf)  # a zero-copy view — nothing is decoded
assert p.name == "Ada"  # read IN PLACE at the schema's offset
```

Reading a schema is two steps, the same two as the Go generator: the
whitespace form is rewritten into the canonical brace form — a near-identity
that only adds the `{`/`}` and `@offset` tokens the brace grammar needs, so a
brace file round-trips byte-for-byte — and then one parser handles both. Field
offsets are assigned from each type's slot width, exactly as in Go, so the two
runtimes lay a schema out identically: bytes built by the bindings generated
here equal bytes built by the bindings Go generates from the same file.

An `interface` also emits an ordinal enum, a handler `Protocol`, a `dispatch`
function, and a typed client that speaks the pipelined envelope below.

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

## Capabilities

`zap.cap` is the capability runtime — signed, attenuable tokens of authority,
a faithful port of [`zap-proto/go/cap`](https://github.com/zap-proto/go/tree/main/cap).
A `Cap` grants a `holder` a `permissions` bitmask over a `target`, issued by an
`issuer`; caps form a chain and `Verifier.verify_chain` walks back to a root.

```python
from zap import cap

signer = cap.Ed25519Signer.generate()
root = cap.issue(
    cap.Issuance(
        kind=int(cap.CapKind.IAM_SESSION),
        permissions=cap.PERM_ATTENUATE,  # may exercise *and* delegate
        expires_at=2_000_000_000,
    ),
    signer,
)
# Narrower child: permissions intersect, expiry only shrinks, parent must carry
# PERM_ATTENUATE (or be a CapKind.DELEGATE cap).
child = cap.attenuate(root, child_holder, cap.PERM_AUDIT, None, 0, signer)
```

`issue` / `attenuate` enforce the SPEC §2.3 delegation gate at mint time;
`Verifier.verify` / `verify_chain` enforce the full invariants with **fail-closed**
scheme dispatch (reserved tag `0x00` and unknown tags refused, never downgraded).
`cap.id` is `SHA-256(canonical_bytes ‖ Sig)` and `canonical_bytes` is the SPEC §3
signed scope — both byte-identical to the Go, Rust, and TypeScript runtimes
(pinned by a cross-language known-answer test). Schemes: Ed25519 (mandatory
bootstrap), ML-DSA-65 (FIPS 204), secp256k1 ECDSA — all real; a missing crypto
backend raises `SchemeUnavailable` (fail-closed). Wire / canonical / CapID are
pure stdlib; signing needs the `[crypto]` extra. The capability layer ships in
all four reference runtimes (Go, Python, Rust, TypeScript).

## Promise pipelining

`zap.pipeline` is the canonical Target-based pipelining model — the byte-for-byte
Python peer of Go's `rpc.Session` / `rpc.Pipeliner` and TypeScript's `Session` /
`Pipeliner`. A call carries a `promise_id`; a dependent call sets `target` to a
prior call's `promise_id`, and the server substitutes that prior call's resolved
body as the dependent's payload before dispatch — so the dependent ships without
waiting for the first answer to round-trip.

```python
from zap import Session, Pipeliner, build_request

sess = Session()
srv = Pipeliner(dispatch)              # dispatch(envelope) -> response envelope

p = sess.next()                        # A: authenticate (target = NO_TARGET)
a = srv.handle(build_request(sess.origin(p, AUTH_ORDINAL, cap_token, auth_req)))
q = sess.next()                        # B: pipeline on A's answer
b = srv.handle(build_request(sess.pipeline(q, p, GET_ORDINAL, cap_token, b"")))
```

The `Pipeliner` queues a dependent whose target has not resolved yet, refuses
(`STATUS_BAD_REQUEST`) one whose target answered non-OK or was `finish`ed, and
never hangs. The `build_request` / `build_response` envelope is byte-identical to
Go's `rpc.BuildRequest` / `BuildResponse` and TypeScript's `buildRequest` /
`buildResponse`, so a pipelined exchange round-trips between all three. (Rust's
`zap-rpc` implements the richer capnp `PromisedAnswer` superset.)

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
