// The frame around every page (ADR-048; docs/design/dashboard.md Section 0.1, screen 5): the
// top bar (logo, the current app's menu, "This computer only", light/dark mode), an optional
// filter bar under it, breadcrumbs when the page has them, and the page. "This computer
// only" reminds that there is no login yet (ADR-049).

import { Breadcrumb, Button, Layout, Tooltip } from 'antd'
import type { ReactNode } from 'react'
import { href, type Query } from '../router.ts'
import type { Mode } from '../theme.ts'
import type { DashboardApp } from './apps.ts'
import { LogoIcon, MoonIcon, SunIcon } from './icons.tsx'

export interface Crumb {
  label: string
  path?: string[] // omitted for the current page
}

interface Props {
  app: DashboardApp | undefined
  page: string | undefined
  crumbs?: Crumb[]
  filterBar?: ReactNode
  query?: Query // the selection, kept on every link
  mode: Mode
  onMode: (mode: Mode) => void
  children: ReactNode
}

export function AppShell({ app, page, crumbs = [], filterBar, query = {}, mode, onMode, children }: Props) {
  const current = page ?? app?.pages[0].key
  return (
    <Layout className="shell">
      <Layout.Header className="shell-top">
        <a href={href([], query)} className="shell-brand" aria-label="LedgerBridge: all apps">
          <LogoIcon />
          <span>LedgerBridge</span>
        </a>
        <nav className="shell-menu" aria-label={app ? `${app.title} menu` : 'Menu'}>
          {app?.pages.map((p) => (
            <a
              key={p.key}
              href={href([app.key, p.key], query)}
              className={p.key === current ? 'shell-menu-item active' : 'shell-menu-item'}
              aria-current={p.key === current ? 'page' : undefined}
            >
              {p.label}
            </a>
          ))}
        </nav>
        <Tooltip title="No login yet: the dashboard runs on this computer only (ADR-049).">
          <span className="local-pill">This computer only</span>
        </Tooltip>
        <Tooltip title={mode === 'dark' ? 'Light mode' : 'Dark mode'}>
          <Button
            type="text"
            className="on-dark"
            aria-label={mode === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
            icon={mode === 'dark' ? <SunIcon /> : <MoonIcon />}
            onClick={() => onMode(mode === 'dark' ? 'light' : 'dark')}
          />
        </Tooltip>
      </Layout.Header>
      {filterBar}
      <Layout.Content className="shell-content">
        {crumbs.length > 0 && (
          <Breadcrumb
            className="shell-crumbs"
            items={crumbs.map((c) => ({ title: c.path ? <a href={href(c.path, query)}>{c.label}</a> : c.label }))}
          />
        )}
        {children}
      </Layout.Content>
    </Layout>
  )
}
