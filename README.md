# ZAP Python

Python bindings for **ZAP** (Zero-Copy App Proto) - high-performance Cap'n Proto RPC for AI agents.

Inspired by [FastMCP](https://github.com/jlowin/fastmcp) with decorator-based API.

## Installation

```bash
pip install zap-protocol
# or
uv add zap-protocol
```

## Quick Start

### Server

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
    return [
        PromptMessage(role="system", content="You are a friendly assistant."),
        PromptMessage(role="assistant", content=f"Hello, {name}! How can I help?"),
    ]

if __name__ == "__main__":
    app.run(port=9999)
```

### Client

```python
import asyncio
from zap import Client

async def main():
    async with Client("localhost:9999") as client:
        # List tools
        tools = await client.list_tools()
        print(f"Available tools: {[t.name for t in tools]}")

        # Call a tool
        result = await client.call_tool("search", {"query": "hello world"})
        print(f"Search result: {result.content}")

        # Read a resource
        content = await client.read_resource("file:///tmp/test.txt")
        print(f"File content: {content.text}")

asyncio.run(main())
```

## Features

- **FastMCP-inspired API**: Decorator-based tool/resource/prompt registration
- **Zero-copy messaging**: Cap'n Proto for efficient serialization
- **Full ZAP protocol**: Tools, resources, prompts, logging
- **Post-quantum crypto**: ML-KEM, ML-DSA, hybrid key exchange
- **W3C DID support**: Decentralized identifiers (did:lux, did:key, did:web)
- **Agent consensus**: Voting-based response aggregation
- **Type-safe**: Full type hints with Pydantic validation

## Agent Consensus

```python
from zap import AgentConsensus, Query, Response, DID, DIDMethod

# Create consensus engine
consensus = AgentConsensus()

# Create agent DID
agent = DID(method=DIDMethod.KEY, id="z6MkAgent...")

# Submit query
query = Query.create("What is the capital of France?", agent)
consensus.submit_query(query)

# Multiple agents respond
response1 = Response.create(query.id, "Paris", agent1, confidence=0.95)
response2 = Response.create(query.id, "Paris", agent2, confidence=0.90)
consensus.submit_response(response1)
consensus.submit_response(response2)

# Agents vote
consensus.vote(query.id, response1.id, voter1)
consensus.vote(query.id, response1.id, voter2)

# Check consensus
result = consensus.try_consensus(query.id)
if result.response:
    print(f"Consensus: {result.response.content} ({result.confidence:.0%})")
```

## Post-Quantum Cryptography

```python
from zap import HybridKeyExchange

# Generate hybrid key pairs (X25519 + ML-KEM)
alice = HybridKeyExchange.generate()
bob = HybridKeyExchange.generate()

# Initiate exchange
x25519_pub, mlkem_pub, nonce = alice.initiate()

# Bob responds
bob_x25519, ciphertext, bob_nonce, bob_secret = bob.respond(
    x25519_pub, mlkem_pub, nonce
)

# Alice finalizes
alice_secret = alice.finalize(bob_x25519, ciphertext, nonce, bob_nonce)

assert alice_secret == bob_secret  # Shared secret established!
```

## Related Packages

- [zap-protocol/zap](https://github.com/zap-protocol/zap) - Core schema + Rust
- [zap-protocol/zap-go](https://github.com/zap-protocol/zap-go) - Go bindings
- [zap-protocol/zap-js](https://github.com/zap-protocol/zap-js) - JavaScript/TypeScript
- [zap-protocol/zap-cpp](https://github.com/zap-protocol/zap-cpp) - C++ bindings
- [zap-protocol/zap-c](https://github.com/zap-protocol/zap-c) - C bindings

## License

MIT
