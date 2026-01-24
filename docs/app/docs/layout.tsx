import { DocsLayout } from 'fumadocs-ui/layouts/docs';
import type { ReactNode } from 'react';
import { source } from '@/lib/source';

export default function Layout({ children }: { children: ReactNode }) {
  return (
    <DocsLayout
      tree={source.pageTree}
      nav={{
        title: 'ZAP Python',
      }}
      sidebar={{
        defaultOpenLevel: 1,
      }}
      links={[
        {
          text: 'GitHub',
          url: 'https://github.com/zap-protocol/zap-py',
        },
      ]}
    >
      {children}
    </DocsLayout>
  );
}
