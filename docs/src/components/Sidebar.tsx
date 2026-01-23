'use client'

import Link from 'next/link'

const navigation = [
  {
    title: 'Getting Started',
    items: [
      { name: 'Installation', href: '#installation' },
      { name: 'Quick Start', href: '#quick-start' },
    ],
  },
  {
    title: 'Server API',
    items: [
      { name: 'ZAP Application', href: '#zap-application' },
      { name: '@app.tool Decorator', href: '#tool-decorator' },
      { name: '@app.resource Decorator', href: '#resource-decorator' },
      { name: '@app.prompt Decorator', href: '#prompt-decorator' },
    ],
  },
  {
    title: 'Client API',
    items: [
      { name: 'Client', href: '#client' },
      { name: 'Async Context Manager', href: '#async-context' },
    ],
  },
  {
    title: 'Advanced',
    items: [
      { name: 'Types', href: '#types' },
      { name: 'Agent Consensus', href: '#consensus' },
      { name: 'Post-Quantum Crypto', href: '#crypto' },
      { name: 'W3C DID Support', href: '#did' },
    ],
  },
  {
    title: 'Examples',
    items: [
      { name: 'Basic Server', href: '#example-server' },
      { name: 'Full Application', href: '#example-full' },
    ],
  },
]

export function Sidebar() {
  return (
    <aside className="fixed left-0 top-0 h-full w-64 border-r border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-900 overflow-y-auto">
      <div className="p-6">
        <Link href="/" className="flex items-center gap-2 no-underline">
          <span className="text-2xl font-bold text-primary-600 dark:text-primary-400">ZAP</span>
          <span className="text-sm text-gray-500 dark:text-gray-400">Python</span>
        </Link>
        <p className="mt-2 text-xs text-gray-500 dark:text-gray-400">
          v0.2.1
        </p>
      </div>

      <nav className="px-4 pb-6">
        {navigation.map((section) => (
          <div key={section.title} className="mb-6">
            <h3 className="px-2 mb-2 text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider">
              {section.title}
            </h3>
            <ul className="space-y-1 list-none pl-0">
              {section.items.map((item) => (
                <li key={item.name} className="list-none">
                  <Link
                    href={item.href}
                    className="block px-2 py-1.5 text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-800 rounded no-underline"
                  >
                    {item.name}
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </nav>

      <div className="px-6 py-4 border-t border-gray-200 dark:border-gray-800">
        <a
          href="https://github.com/zap-protocol/zap-py"
          className="text-sm text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 no-underline"
          target="_blank"
          rel="noopener noreferrer"
        >
          GitHub
        </a>
      </div>
    </aside>
  )
}
