import { CodeBlock } from './CodeBlock'

export function Content() {
  return (
    <div className="max-w-4xl px-8 py-12">
      {/* Installation */}
      <section id="installation">
        <h2>Installation</h2>
        <p>Install ZAP Python using pip or uv:</p>
        <CodeBlock language="bash">{`pip install zap-protocol

# Or with uv (recommended)
uv add zap-protocol`}</CodeBlock>
      </section>

      {/* Quick Start */}
      <section id="quick-start">
        <h2>Quick Start</h2>
        <p>
          ZAP Python uses a FastMCP-inspired decorator API for building agent servers.
          Define tools, resources, and prompts using simple decorators.
        </p>

        <h3>Server</h3>
        <CodeBlock language="python">{`from zap import ZAP, PromptMessage

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
    app.run(port=9999)`}</CodeBlock>

        <h3>Client</h3>
        <CodeBlock language="python">{`import asyncio
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

asyncio.run(main())`}</CodeBlock>
      </section>

      {/* ZAP Application */}
      <section id="zap-application">
        <h2>ZAP Application</h2>
        <p>
          The <code>ZAP</code> class is the main entry point for building servers.
          It manages tool, resource, and prompt registration.
        </p>

        <CodeBlock language="python">{`from zap import ZAP

# Basic initialization
app = ZAP("my-agent")

# With version and capability options
app = ZAP(
    "my-agent",
    version="1.0.0",
    enable_tools=True,      # Enable tools (default: True)
    enable_resources=True,  # Enable resources (default: True)
    enable_prompts=True,    # Enable prompts (default: True)
    enable_logging=True,    # Enable logging (default: True)
)

# Run the server
app.run(host="0.0.0.0", port=9999, transport="tcp")`}</CodeBlock>

        <h3>Server Info</h3>
        <p>Access server metadata via the <code>info</code> property:</p>
        <CodeBlock language="python">{`info = app.info
print(f"Server: {info.name} v{info.version}")
print(f"Capabilities: {info.capabilities}")`}</CodeBlock>
      </section>

      {/* Tool Decorator */}
      <section id="tool-decorator">
        <h2>@app.tool Decorator</h2>
        <p>
          Register functions as callable tools. Type hints are automatically converted
          to JSON Schema for input validation.
        </p>

        <h3>Basic Usage</h3>
        <CodeBlock language="python">{`@app.tool
def add(a: int, b: int) -> int:
    """Add two numbers together"""
    return a + b`}</CodeBlock>

        <h3>Custom Name and Description</h3>
        <CodeBlock language="python">{`@app.tool(name="calculator_add", description="Add two numbers")
def add(a: int, b: int) -> int:
    return a + b`}</CodeBlock>

        <h3>With Annotations</h3>
        <CodeBlock language="python">{`@app.tool(annotations={"category": "math", "safe": "true"})
def multiply(a: float, b: float) -> float:
    """Multiply two numbers"""
    return a * b`}</CodeBlock>

        <h3>Async Tools</h3>
        <CodeBlock language="python">{`@app.tool
async def fetch_data(url: str) -> dict:
    """Fetch JSON data from a URL"""
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        return response.json()`}</CodeBlock>

        <h3>Complex Types</h3>
        <CodeBlock language="python">{`from pydantic import BaseModel

class SearchResult(BaseModel):
    title: str
    score: float
    url: str

@app.tool
def search(query: str, limit: int = 10) -> list[SearchResult]:
    """Search the knowledge base"""
    return [
        SearchResult(title="Result 1", score=0.95, url="https://example.com/1"),
        SearchResult(title="Result 2", score=0.87, url="https://example.com/2"),
    ]`}</CodeBlock>
      </section>

      {/* Resource Decorator */}
      <section id="resource-decorator">
        <h2>@app.resource Decorator</h2>
        <p>
          Register functions as resource providers. Resources are accessed via URI templates
          with parameter extraction.
        </p>

        <h3>Basic Usage</h3>
        <CodeBlock language="python">{`@app.resource("file://{path}")
def read_file(path: str) -> str:
    """Read a file from disk"""
    return open(path).read()`}</CodeBlock>

        <h3>With MIME Type</h3>
        <CodeBlock language="python">{`@app.resource("image://{path}", mime_type="image/png")
def read_image(path: str) -> bytes:
    """Read an image file"""
    return open(path, "rb").read()`}</CodeBlock>

        <h3>Multiple Parameters</h3>
        <CodeBlock language="python">{`@app.resource("db://{database}/{table}/{id}")
def get_record(database: str, table: str, id: str) -> dict:
    """Get a database record"""
    return {"database": database, "table": table, "id": id}`}</CodeBlock>

        <h3>Custom Name</h3>
        <CodeBlock language="python">{`@app.resource(
    "config://{key}",
    name="configuration",
    description="Read application configuration",
    mime_type="application/json",
)
def get_config(key: str) -> str:
    return json.dumps(config.get(key))`}</CodeBlock>
      </section>

      {/* Prompt Decorator */}
      <section id="prompt-decorator">
        <h2>@app.prompt Decorator</h2>
        <p>
          Register functions as prompt generators. Prompts return a list of messages
          that can be used to initialize conversations.
        </p>

        <h3>Basic Usage</h3>
        <CodeBlock language="python">{`from zap import PromptMessage

@app.prompt
def greeting(name: str) -> list[PromptMessage]:
    """Generate a personalized greeting"""
    return [
        PromptMessage(role="system", content="You are a friendly assistant."),
        PromptMessage(role="assistant", content=f"Hello, {name}! How can I help?"),
    ]`}</CodeBlock>

        <h3>With Optional Arguments</h3>
        <CodeBlock language="python">{`@app.prompt
def code_review(
    language: str,
    style: str = "concise",
    focus: str = "bugs"
) -> list[PromptMessage]:
    """Generate a code review prompt"""
    return [
        PromptMessage(
            role="system",
            content=f"You are a {language} code reviewer. "
                    f"Be {style} and focus on {focus}."
        ),
    ]`}</CodeBlock>

        <h3>Multi-turn Conversations</h3>
        <CodeBlock language="python">{`@app.prompt
def interview(role: str, company: str) -> list[PromptMessage]:
    """Generate an interview conversation starter"""
    return [
        PromptMessage(
            role="system",
            content=f"You are interviewing for a {role} position at {company}."
        ),
        PromptMessage(
            role="user",
            content="Tell me about yourself."
        ),
        PromptMessage(
            role="assistant",
            content=f"I'm excited about the {role} opportunity at {company}..."
        ),
    ]`}</CodeBlock>
      </section>

      {/* Client */}
      <section id="client">
        <h2>Client API</h2>
        <p>
          The <code>Client</code> class connects to ZAP servers and provides
          methods for calling tools, reading resources, and getting prompts.
        </p>

        <h3>Connection</h3>
        <CodeBlock language="python">{`from zap import Client

# Using async context manager (recommended)
async with Client("localhost:9999") as client:
    tools = await client.list_tools()

# Manual connection
client = Client("localhost:9999")
await client.connect()
# ... use client ...
await client.close()`}</CodeBlock>

        <h3>Listing Capabilities</h3>
        <CodeBlock language="python">{`# List available tools
tools = await client.list_tools()
for tool in tools:
    print(f"{tool.name}: {tool.description}")

# List available resources
resources = await client.list_resources()
for resource in resources:
    print(f"{resource.uri}: {resource.name}")

# List available prompts
prompts = await client.list_prompts()
for prompt in prompts:
    print(f"{prompt.name}: {prompt.description}")`}</CodeBlock>

        <h3>Calling Tools</h3>
        <CodeBlock language="python">{`result = await client.call_tool("search", {"query": "hello", "limit": 5})

if result.error:
    print(f"Error: {result.error}")
else:
    print(f"Result: {result.content}")`}</CodeBlock>

        <h3>Reading Resources</h3>
        <CodeBlock language="python">{`content = await client.read_resource("file:///tmp/data.txt")

if content.text:
    print(f"Text: {content.text}")
elif content.blob:
    print(f"Binary: {len(content.blob)} bytes")`}</CodeBlock>

        <h3>Getting Prompts</h3>
        <CodeBlock language="python">{`messages = await client.get_prompt("greeting", {"name": "Alice"})

for msg in messages:
    print(f"[{msg.role}]: {msg.content}")`}</CodeBlock>
      </section>

      {/* Async Context */}
      <section id="async-context">
        <h2>Async Context Manager</h2>
        <p>
          The client supports async context manager protocol for automatic
          connection management:
        </p>
        <CodeBlock language="python">{`async def main():
    async with Client("localhost:9999") as client:
        # Connection is automatically established
        tools = await client.list_tools()

        # Call tools, read resources, etc.
        result = await client.call_tool("search", {"query": "test"})

    # Connection is automatically closed

asyncio.run(main())`}</CodeBlock>
      </section>

      {/* Types */}
      <section id="types">
        <h2>Types</h2>
        <p>ZAP Python provides typed dataclasses for all protocol types:</p>

        <h3>Tool Types</h3>
        <CodeBlock language="python">{`from zap import Tool, ToolResult

# Tool definition
tool = Tool(
    name="search",
    description="Search the knowledge base",
    schema={"type": "object", "properties": {...}},
    annotations={"category": "search"},
)

# Tool result
result = ToolResult(
    id="search",
    content=b'{"results": [...]}',
    error="",  # Empty if successful
    metadata={"duration_ms": "42"},
)`}</CodeBlock>

        <h3>Resource Types</h3>
        <CodeBlock language="python">{`from zap import Resource, ResourceContent

# Resource definition
resource = Resource(
    uri="file://{path}",
    name="file_reader",
    description="Read files from disk",
    mime_type="text/plain",
    annotations={},
)

# Resource content
content = ResourceContent(
    uri="file:///tmp/test.txt",
    mime_type="text/plain",
    text="Hello, World!",  # For text content
    blob=None,             # For binary content
)`}</CodeBlock>

        <h3>Prompt Types</h3>
        <CodeBlock language="python">{`from zap import Prompt, PromptMessage, PromptArgument

# Prompt definition
prompt = Prompt(
    name="greeting",
    description="Generate a greeting",
    arguments=[
        PromptArgument(name="name", description="User name", required=True),
    ],
)

# Prompt message
message = PromptMessage(
    role="assistant",  # "user", "assistant", or "system"
    content="Hello!",
)`}</CodeBlock>

        <h3>Server Types</h3>
        <CodeBlock language="python">{`from zap import ServerInfo, Capabilities

# Server capabilities
capabilities = Capabilities(
    tools=True,
    resources=True,
    prompts=True,
    logging=True,
)

# Server info
info = ServerInfo(
    name="my-agent",
    version="1.0.0",
    capabilities=capabilities,
)`}</CodeBlock>
      </section>

      {/* Consensus */}
      <section id="consensus">
        <h2>Agent Consensus</h2>
        <p>
          ZAP Python includes a voting-based consensus mechanism for
          coordinating responses from multiple AI agents.
        </p>

        <CodeBlock language="python">{`from zap import AgentConsensus, Query, Response, DID, DIDMethod

# Create consensus engine
consensus = AgentConsensus()

# Create agent DIDs
agent1 = DID(method=DIDMethod.KEY, id="z6MkAgent1...")
agent2 = DID(method=DIDMethod.KEY, id="z6MkAgent2...")
voter1 = DID(method=DIDMethod.KEY, id="z6MkVoter1...")
voter2 = DID(method=DIDMethod.KEY, id="z6MkVoter2...")

# Submit a query
query = Query.create("What is the capital of France?", agent1)
consensus.submit_query(query)

# Multiple agents respond
response1 = Response.create(query.id, "Paris", agent1, confidence=0.95)
response2 = Response.create(query.id, "Paris", agent2, confidence=0.90)
consensus.submit_response(response1)
consensus.submit_response(response2)

# Agents vote on responses
consensus.vote(query.id, response1.id, voter1)
consensus.vote(query.id, response1.id, voter2)

# Check for consensus
result = consensus.try_consensus(query.id)
if result.response:
    print(f"Consensus: {result.response.content}")
    print(f"Confidence: {result.confidence:.0%}")
    print(f"Votes: {result.votes}/{result.total_voters}")`}</CodeBlock>

        <h3>Configuration</h3>
        <CodeBlock language="python">{`from zap.consensus import ConsensusConfig

config = ConsensusConfig(
    threshold=0.5,       # Required vote fraction (default: 0.5)
    min_responses=1,     # Minimum responses before check (default: 1)
    min_votes=3,         # Minimum votes before check (default: 3)
    timeout_secs=60,     # Query timeout in seconds (default: 60)
)

consensus = AgentConsensus(config=config)`}</CodeBlock>
      </section>

      {/* Crypto */}
      <section id="crypto">
        <h2>Post-Quantum Cryptography</h2>
        <p>
          ZAP Python supports post-quantum cryptographic algorithms for
          future-proof security.
        </p>

        <h3>Hybrid Key Exchange</h3>
        <CodeBlock language="python">{`from zap import HybridKeyExchange

# Generate hybrid key pairs (X25519 + ML-KEM)
alice = HybridKeyExchange.generate()
bob = HybridKeyExchange.generate()

# Alice initiates exchange
x25519_pub, mlkem_pub, nonce = alice.initiate()

# Bob responds
bob_x25519, ciphertext, bob_nonce, bob_secret = bob.respond(
    x25519_pub, mlkem_pub, nonce
)

# Alice finalizes
alice_secret = alice.finalize(bob_x25519, ciphertext, nonce, bob_nonce)

assert alice_secret == bob_secret  # Shared secret established!`}</CodeBlock>

        <h3>ML-KEM (FIPS 203)</h3>
        <CodeBlock language="python">{`from zap import MLKEMKeyPair

# Generate ML-KEM-768 key pair
keypair = MLKEMKeyPair.generate()

# Encapsulate a shared secret
ciphertext, shared_secret = keypair.encapsulate()

# Decapsulate (on receiver side)
recovered_secret = keypair.decapsulate(ciphertext)`}</CodeBlock>

        <h3>ML-DSA (FIPS 204)</h3>
        <CodeBlock language="python">{`from zap import MLDSAKeyPair

# Generate ML-DSA-65 key pair
keypair = MLDSAKeyPair.generate()

# Sign a message
message = b"Hello, World!"
signature = keypair.sign(message)

# Verify signature
is_valid = keypair.verify(message, signature)`}</CodeBlock>
      </section>

      {/* DID */}
      <section id="did">
        <h2>W3C DID Support</h2>
        <p>
          ZAP Python supports W3C Decentralized Identifiers (DIDs) for
          agent identity management.
        </p>

        <h3>Creating DIDs</h3>
        <CodeBlock language="python">{`from zap import DID, DIDMethod

# Create a did:key from a public key
did = DID.from_public_key(public_key_bytes)
print(did)  # did:key:z6Mk...

# Create a did:web from a domain
did = DID.from_web("example.com", "agents/alice")
print(did)  # did:web:example.com:agents:alice

# Create manually
did = DID(method=DIDMethod.LUX, id="0x1234...")`}</CodeBlock>

        <h3>Parsing DIDs</h3>
        <CodeBlock language="python">{`# Parse a DID string
did = DID.parse("did:key:z6MkAgent123...")
print(did.method)  # DIDMethod.KEY
print(did.id)      # z6MkAgent123...

# Validate
if did.is_valid():
    print("Valid DID")`}</CodeBlock>

        <h3>Supported Methods</h3>
        <CodeBlock language="python">{`from zap import DIDMethod

DIDMethod.LUX  # did:lux - Lux blockchain-anchored DIDs
DIDMethod.KEY  # did:key - Self-certifying DIDs from keys
DIDMethod.WEB  # did:web - DNS-based DIDs`}</CodeBlock>
      </section>

      {/* Example Server */}
      <section id="example-server">
        <h2>Example: Basic Server</h2>
        <CodeBlock language="python">{`from zap import ZAP, PromptMessage

app = ZAP("calculator", version="1.0.0")

@app.tool
def add(a: float, b: float) -> float:
    """Add two numbers"""
    return a + b

@app.tool
def subtract(a: float, b: float) -> float:
    """Subtract b from a"""
    return a - b

@app.tool
def multiply(a: float, b: float) -> float:
    """Multiply two numbers"""
    return a * b

@app.tool
def divide(a: float, b: float) -> float:
    """Divide a by b"""
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b

@app.prompt
def math_assistant() -> list[PromptMessage]:
    """Initialize a math assistant conversation"""
    return [
        PromptMessage(
            role="system",
            content="You are a helpful math assistant with access to "
                    "add, subtract, multiply, and divide tools."
        ),
    ]

if __name__ == "__main__":
    app.run(port=9999)`}</CodeBlock>
      </section>

      {/* Example Full */}
      <section id="example-full">
        <h2>Example: Full Application</h2>
        <CodeBlock language="python">{`"""
Full ZAP application with tools, resources, prompts, and consensus.
"""
import asyncio
import json
from pathlib import Path

from zap import (
    ZAP,
    Client,
    PromptMessage,
    AgentConsensus,
    Query,
    Response,
    DID,
    DIDMethod,
)

# Initialize application
app = ZAP("knowledge-agent", version="1.0.0")

# In-memory knowledge base
knowledge_base = {
    "python": "Python is a high-level programming language.",
    "rust": "Rust is a systems programming language focused on safety.",
    "zap": "ZAP is a high-performance RPC protocol for AI agents.",
}


# ============ Tools ============

@app.tool
def search(query: str, limit: int = 5) -> list[dict]:
    """Search the knowledge base"""
    results = []
    query_lower = query.lower()
    for key, value in knowledge_base.items():
        if query_lower in key or query_lower in value.lower():
            results.append({
                "topic": key,
                "content": value,
                "score": 1.0 if query_lower == key else 0.5,
            })
    return sorted(results, key=lambda x: x["score"], reverse=True)[:limit]


@app.tool
def add_knowledge(topic: str, content: str) -> dict:
    """Add a new entry to the knowledge base"""
    knowledge_base[topic.lower()] = content
    return {"status": "added", "topic": topic}


@app.tool
async def fetch_url(url: str) -> str:
    """Fetch content from a URL"""
    import httpx
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        return response.text[:1000]  # Limit response size


# ============ Resources ============

@app.resource("knowledge://{topic}")
def get_knowledge(topic: str) -> str:
    """Get knowledge about a topic"""
    topic_lower = topic.lower()
    if topic_lower in knowledge_base:
        return knowledge_base[topic_lower]
    return f"No knowledge found about: {topic}"


@app.resource("file://{path}", mime_type="text/plain")
def read_file(path: str) -> str:
    """Read a local file"""
    return Path(path).read_text()


@app.resource("stats://summary", mime_type="application/json")
def get_stats() -> str:
    """Get knowledge base statistics"""
    return json.dumps({
        "total_topics": len(knowledge_base),
        "topics": list(knowledge_base.keys()),
    })


# ============ Prompts ============

@app.prompt
def knowledge_assistant(topic: str = "general") -> list[PromptMessage]:
    """Initialize a knowledge assistant conversation"""
    return [
        PromptMessage(
            role="system",
            content=f"You are a knowledgeable assistant specializing in {topic}. "
                    f"You have access to a knowledge base with {len(knowledge_base)} topics."
        ),
        PromptMessage(
            role="assistant",
            content=f"Hello! I'm ready to help you learn about {topic}. "
                    "What would you like to know?"
        ),
    ]


@app.prompt
def researcher(depth: str = "basic") -> list[PromptMessage]:
    """Initialize a research conversation"""
    detail = "provide brief overviews" if depth == "basic" else "dive deep into details"
    return [
        PromptMessage(
            role="system",
            content=f"You are a research assistant. When answering questions, {detail}."
        ),
    ]


# ============ Main ============

async def demo_client():
    """Demonstrate client usage"""
    async with Client("localhost:9999") as client:
        # List tools
        tools = await client.list_tools()
        print(f"Available tools: {[t.name for t in tools]}")

        # Search knowledge
        result = await client.call_tool("search", {"query": "python"})
        print(f"Search result: {result.content}")

        # Read resource
        content = await client.read_resource("knowledge://zap")
        print(f"ZAP knowledge: {content.text}")

        # Get prompt
        messages = await client.get_prompt(
            "knowledge_assistant",
            {"topic": "programming"}
        )
        for msg in messages:
            print(f"[{msg.role}]: {msg.content}")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "client":
        asyncio.run(demo_client())
    else:
        app.run(port=9999)`}</CodeBlock>
      </section>

      {/* Footer */}
      <footer className="mt-16 pt-8 border-t border-gray-200 dark:border-gray-800">
        <div className="flex justify-between items-center text-sm text-gray-500">
          <p>
            Part of the <a href="https://github.com/zap-protocol">ZAP Protocol</a> family
          </p>
          <p>MIT License</p>
        </div>
        <div className="mt-4 flex gap-4 text-sm">
          <a href="https://github.com/zap-protocol/zap">Core (Rust)</a>
          <a href="https://github.com/zap-protocol/zap-go">Go</a>
          <a href="https://github.com/zap-protocol/zap-js">JavaScript</a>
          <a href="https://github.com/zap-protocol/zap-cpp">C++</a>
          <a href="https://github.com/zap-protocol/zap-c">C</a>
        </div>
      </footer>
    </div>
  )
}
