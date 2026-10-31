// The frame around every page (docs/design/dashboard.md Section 0.2, screen 7): the charcoal
// side bar on the left (collapsible; collapsed on narrow screens at first), and on the right
// the top filter bar above the page.

import { Layout } from 'antd'
import { useState, type ReactNode } from 'react'

interface Props {
  sideBar: (collapsed: boolean, onCollapse: (collapsed: boolean) => void) => ReactNode
  topBar: ReactNode
  children: ReactNode
}

const NARROW = '(max-width: 800px)'

export function AppShell({ sideBar, topBar, children }: Props) {
  const [collapsed, setCollapsed] = useState(() => window.matchMedia(NARROW).matches)
  return (
    <Layout className={collapsed ? 'shell side-collapsed' : 'shell'}>
      {sideBar(collapsed, setCollapsed)}
      <div className="shell-main">
        {topBar}
        <Layout.Content className="shell-content">{children}</Layout.Content>
      </div>
    </Layout>
  )
}
