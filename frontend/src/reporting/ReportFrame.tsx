// The frame of a report page (docs/design/dashboard.md Sections 0.1, 0.3 and 0.4): the title
// with the selected companies, the period and "combined, without inter-company eliminations",
// and "What is this?" (the options side panel is gone: each card and column explains itself on
// hover). The page puts its figures inside.

import { Typography } from 'antd'
import type { ReactNode } from 'react'
import type { Company, PeriodOut } from '../api/types.ts'
import { COMBINED_NOTE } from '../apps/dashboard/words.ts'
import { formatDate } from '../format.ts'
import type { Query } from '../router.ts'
import { WhatIsThis } from './WhatIsThis.tsx'

export interface PanelProps {
  query: Query // the selection, kept on every link
}

interface Props extends PanelProps {
  title: string // "Monthly sales"
  page: string // where saved views are kept
  companies: Company[] // the selected ones
  period: PeriodOut | undefined
  combined: boolean
  help: (sourceName: string) => ReactNode
  children: ReactNode
}

export function ReportFrame(props: Props) {
  const { companies } = props
  const sourceName = companies[0]?.health.source_name ?? 'the source'
  return (
    <div className="report-page">
      <div className="report-main">
        <div className="report-head">
          <div>
            <Typography.Title level={2} className="report-title">
              {props.title} · {companies.map((c) => c.name).join(' + ')}
            </Typography.Title>
            {props.period && (
              <Typography.Text type="secondary">
                {formatDate(props.period.start)} to {formatDate(props.period.end)}
                {props.combined ? ` · ${COMBINED_NOTE}` : ''}
              </Typography.Text>
            )}
          </div>
          <div className="report-toolbar">
            <WhatIsThis>{props.help(sourceName)}</WhatIsThis>
          </div>
        </div>
        {props.children}
      </div>
    </div>
  )
}
