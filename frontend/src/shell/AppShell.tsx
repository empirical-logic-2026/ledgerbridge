// The frame around every page (docs/design/dashboard.md Section 0.4, ADR-050): the dark top
// bar with the module tabs and period toggles, the page header, then the page.

import { Layout } from 'antd'
import type { ReactNode } from 'react'

interface Props {
  topBar: ReactNode
  header: ReactNode
  children: ReactNode
}

export function AppShell({ topBar, header, children }: Props) {
  return (
    <Layout className="shell">
      {topBar}
      {header}
      <Layout.Content className="shell-content">{children}</Layout.Content>
    </Layout>
  )
}
