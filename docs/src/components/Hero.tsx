export function Hero() {
  return (
    <header className="bg-gradient-to-r from-primary-600 to-primary-800 text-white py-16 px-8">
      <div className="max-w-4xl">
        <h1 className="text-5xl font-bold mb-4 border-none mt-0">
          ZAP Python
        </h1>
        <p className="text-xl text-primary-100 mb-6">
          High-performance Cap&apos;n Proto RPC for AI agents.
          <br />
          FastMCP-inspired decorator API for building agent servers.
        </p>
        <div className="flex gap-4">
          <a
            href="#quick-start"
            className="px-6 py-3 bg-white text-primary-700 font-semibold rounded-lg hover:bg-primary-50 no-underline"
          >
            Get Started
          </a>
          <a
            href="https://github.com/zap-protocol/zap-py"
            className="px-6 py-3 border-2 border-white text-white font-semibold rounded-lg hover:bg-white/10 no-underline"
            target="_blank"
            rel="noopener noreferrer"
          >
            GitHub
          </a>
        </div>
      </div>
    </header>
  )
}
