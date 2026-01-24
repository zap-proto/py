import Link from 'next/link';

export default function HomePage() {
  return (
    <main className="flex flex-1 flex-col items-center justify-center text-center px-4 py-16">
      <h1 className="text-4xl font-bold mb-4">ZAP Python</h1>
      <p className="text-fd-muted-foreground text-lg mb-8 max-w-2xl">
        High-performance ZAP RPC for Python AI agents with FastMCP-style decorators
        and post-quantum security.
      </p>
      <div className="flex gap-4">
        <Link
          href="/docs"
          className="rounded-lg bg-fd-primary px-6 py-3 text-fd-primary-foreground font-medium hover:opacity-90 transition-opacity"
        >
          Get Started
        </Link>
        <Link
          href="https://github.com/zap-protocol/zap-py"
          className="rounded-lg border border-fd-border px-6 py-3 font-medium hover:bg-fd-accent transition-colors"
        >
          GitHub
        </Link>
      </div>
      <div className="mt-16 grid grid-cols-1 md:grid-cols-3 gap-8 max-w-4xl">
        <div className="p-6 rounded-lg border border-fd-border">
          <h3 className="font-semibold mb-2">FastMCP-Style API</h3>
          <p className="text-fd-muted-foreground text-sm">
            Decorator-based tool, resource, and prompt registration inspired by FastMCP.
          </p>
        </div>
        <div className="p-6 rounded-lg border border-fd-border">
          <h3 className="font-semibold mb-2">Zero-Copy Performance</h3>
          <p className="text-fd-muted-foreground text-sm">
            Built on ZAP for minimal serialization overhead and maximum throughput.
          </p>
        </div>
        <div className="p-6 rounded-lg border border-fd-border">
          <h3 className="font-semibold mb-2">Post-Quantum Security</h3>
          <p className="text-fd-muted-foreground text-sm">
            ML-KEM-768 and ML-DSA-65 cryptography for future-proof agent communication.
          </p>
        </div>
      </div>
    </main>
  );
}
