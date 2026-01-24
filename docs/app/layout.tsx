import './global.css';
import type { Metadata, Viewport } from 'next';
import type { ReactNode } from 'react';
import { RootProvider } from 'fumadocs-ui/provider';

export const metadata: Metadata = {
  title: {
    template: '%s | ZAP Python',
    default: 'ZAP Python Documentation',
  },
  description: 'Python bindings for ZAP - Zero-Copy App Proto for AI agent communication',
  metadataBase: new URL('https://zap-protocol.github.io/zap-py'),
};

export const viewport: Viewport = {
  themeColor: [
    { media: '(prefers-color-scheme: dark)', color: '#0a0a0a' },
    { media: '(prefers-color-scheme: light)', color: '#ffffff' },
  ],
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className="flex flex-col min-h-screen">
        <RootProvider>{children}</RootProvider>
      </body>
    </html>
  );
}
