// The side bar (docs/design/dashboard.md Section 0.2, screen 7): charcoal, collapsible, the
// built pages grouped (Overview, Sales, Purchases, Statements, Books, Parties, Data), and at
// its foot "This computer only" (no login yet: ADR-049), the last sync, whether the source
// had the companies loaded and the checks passed, and light/dark mode.

import { Button, Tooltip } from 'antd'
import type { Company } from '../api/types.ts'
import { href, type Query } from '../router.ts'
import type { Mode } from '../theme.ts'
import { HOME, builtNav } from './nav.ts'
import { LogoIcon, MoonIcon, SunIcon } from './icons.tsx'
import { syncStatus } from './status.ts'

interface Props {
  current: [string, string] | undefined // group and page shown
  query: Query // the selection, kept on every link
  companies: Company[] // every visible company (for the status)
  mode: Mode
  onMode: (mode: Mode) => void
  collapsed: boolean
  onCollapse: (collapsed: boolean) => void
}

export function SideBar({ current, query, companies, mode, onMode, collapsed, onCollapse }: Props) {
  const status = syncStatus(companies)
  return (
    <nav className={collapsed ? 'side-bar collapsed' : 'side-bar'} aria-label="Pages">
      <div className="side-head">
        <a href={href([...HOME], query)} className="side-brand" aria-label="LedgerBridge: Dashboard">
          <LogoIcon />
          {!collapsed && <span>LedgerBridge</span>}
        </a>
        <Button
          type="text"
          className="on-dark side-toggle"
          aria-label={collapsed ? 'Open the side bar' : 'Close the side bar'}
          aria-expanded={!collapsed}
          onClick={() => onCollapse(!collapsed)}
        >
          {collapsed ? '»' : '«'}
        </Button>
      </div>
      {!collapsed && (
        <>
          <div className="side-groups">
            {builtNav().map((group) => (
              <section key={group.key} aria-label={group.label}>
                <h2 className="side-group">{group.label}</h2>
                {group.pages.map((p) => {
                  const active = current?.[0] === group.key && current?.[1] === p.key
                  return (
                    <a key={p.key} href={href([group.key, p.key], query)} className={active ? 'side-item active' : 'side-item'} aria-current={active ? 'page' : undefined}>
                      {p.label}
                    </a>
                  )
                })}
              </section>
            ))}
          </div>
          <div className="side-foot">
            {status && <p className={status.ok ? 'side-status' : 'side-status side-status-bad'}>{status.text}</p>}
            <div className="side-foot-row">
              <Tooltip title="No login yet: the dashboard runs on this computer only (ADR-049).">
                <span>This computer only</span>
              </Tooltip>
              <Button
                type="text"
                className="on-dark"
                aria-label={mode === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
                icon={mode === 'dark' ? <SunIcon /> : <MoonIcon />}
                onClick={() => onMode(mode === 'dark' ? 'light' : 'dark')}
              />
            </div>
          </div>
        </>
      )}
    </nav>
  )
}
