import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'ZAP Python Documentation',
  description: 'High-performance Cap\'n Proto RPC for AI agents - Python bindings',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-white dark:bg-gray-950">
        {children}
      </body>
    </html>
  )
}
