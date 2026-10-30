// The frame around every page (ADR-048): the top bar (product name, apps menu, the current
// app's menu, the company and period controls, light/dark mode), the breadcrumbs, and the
// page itself. The "This computer only" tag reminds that there is no login yet (ADR-049).

import { Breadcrumb, Button, Dropdown, Flex, Layout, Menu, Tag, Tooltip, Typography } from 'antd'
import type { ReactNode } from 'react'
import { href, navigate, type Query } from '../router.ts'
import type { Mode } from '../theme.ts'
import { APPS, type DashboardApp } from './apps.ts'
import { AppsIcon, MoonIcon, SunIcon } from './icons.tsx'

export interface Crumb {
  label: string
  path?: string[] // omitted for the current page
}

interface Props {
  app: DashboardApp | undefined
  page: string | undefined
  crumbs: Crumb[]
  controls?: ReactNode // company switcher, period controls
  query?: Query // the selection, kept on every link
  mode: Mode
  onMode: (mode: Mode) => void
  children: ReactNode
}

export function AppShell({ app, page, crumbs, controls, query = {}, mode, onMode, children }: Props) {
  const appsMenu = {
    items: [
      { key: '', label: 'All apps' },
      ...APPS.map((a) => ({ key: a.key, label: a.title })),
    ],
    onClick: ({ key }: { key: string }) => navigate(key ? [key] : [], query),
  }
  return (
    <Layout className="shell">
      <Layout.Header className="shell-top">
        <Flex align="center" gap={12} className="shell-top-row">
          <Dropdown menu={appsMenu} trigger={['click']}>
            <Button type="text" className="on-dark" aria-label="Apps" icon={<AppsIcon />} />
          </Dropdown>
          <a href={href([], query)} className="shell-brand">
            LedgerBridge
          </a>
          {app && (
            <Menu
              mode="horizontal"
              theme="dark"
              className="shell-app-menu"
              selectedKeys={[page ?? app.menu[0].key]}
              items={app.menu.map((m) => ({ key: m.key, label: <a href={href([app.key, m.key], query)}>{m.label}</a> }))}
            />
          )}
          <Flex align="center" gap={8} wrap className="shell-controls">
            {controls}
            <Tooltip title="No login yet: the dashboard runs on this computer only (ADR-049).">
              <Tag className="local-tag">This computer only</Tag>
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
          </Flex>
        </Flex>
      </Layout.Header>
      <div className="shell-crumbs">
        <Breadcrumb
          items={crumbs.map((c) => ({
            title: c.path ? <a href={href(c.path, query)}>{c.label}</a> : <Typography.Text strong>{c.label}</Typography.Text>,
          }))}
        />
      </div>
      <Layout.Content className="shell-content">{children}</Layout.Content>
    </Layout>
  )
}
