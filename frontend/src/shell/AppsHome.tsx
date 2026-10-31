// The apps home (docs/design/dashboard.md Section 0.1, screen 1): a greeting, the sync status,
// and a tile per app with its icon and what it is for.

import { Typography } from 'antd'
import type { ReactNode } from 'react'
import { href, type Query } from '../router.ts'
import { APPS, type AppIcon } from './apps.ts'
import { greeting } from './greeting.ts'
import { ReportsIcon } from './icons.tsx'

const ICONS: Record<AppIcon, ReactNode> = { reports: <ReportsIcon /> }

interface Props {
  query?: Query
  status?: ReactNode // the sync status pill
  sourceName: string // "Tally"
  now: Date
}

export function AppsHome({ query = {}, status, sourceName, now }: Props) {
  return (
    <div className="apps-home">
      <div className="apps-home-head">
        <div>
          <Typography.Title level={1} className="apps-home-title">
            {greeting(now)}
          </Typography.Title>
          <Typography.Text type="secondary" className="apps-home-sub">
            {`Choose an app. Everything updates automatically from ${sourceName}.`}
          </Typography.Text>
        </div>
        {status}
      </div>
      <div className="tiles">
        {APPS.map((app) => (
          <a key={app.key} href={href([app.key], query)} className="tile">
            <span className={`tile-icon tile-icon-${app.icon}`}>{ICONS[app.icon]}</span>
            <span className="tile-title">{app.title}</span>
            <span className="tile-text">{app.description}</span>
          </a>
        ))}
      </div>
    </div>
  )
}
