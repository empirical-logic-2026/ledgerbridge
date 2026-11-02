// The frame of a report page (docs/design/dashboard.md Sections 0.1 and 0.3): the title with
// the selected companies, the period and "combined, without inter-company eliminations", the
// Options button, and the options side panel with "Open related", saved views and "What is
// this?". The page puts its figures inside.

import { Button, Typography } from 'antd'
import type { ReactNode } from 'react'
import type { Company, PeriodOut } from '../api/types.ts'
import { COMBINED_NOTE } from '../apps/dashboard/DashboardHome.tsx'
import { formatDate } from '../format.ts'
import type { Query } from '../router.ts'
import { OptionsPanel, type Related } from './OptionsPanel.tsx'

export interface PanelProps {
  panelOpen: boolean
  onPanel: (open: boolean) => void
  currentQuery: string
  onApplyView: (query: string) => void
  related: Related[]
  query: Query
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
    <div className={props.panelOpen ? 'report-page with-panel' : 'report-page'}>
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
          <div className="report-toolbar">{!props.panelOpen && <Button onClick={() => props.onPanel(true)}>Options</Button>}</div>
        </div>
        {props.children}
      </div>
      {props.panelOpen && (
        <OptionsPanel
          title={`${props.title} options`}
          page={props.page}
          matching={undefined}
          companiesLabel={companies.length === 1 ? companies[0].name : `all ${companies.length} companies`}
          sourceName={sourceName}
          related={props.related}
          query={props.query}
          currentQuery={props.currentQuery}
          onApplyView={props.onApplyView}
          help={props.help(sourceName)}
          onClose={() => props.onPanel(false)}
        />
      )}
    </div>
  )
}
