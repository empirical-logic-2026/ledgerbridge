// The dashboard: which page the URL asks for, the selection (companies, year, months or
// dates, compare), and the shell around the page. Pages: the apps home ("#/") and the Reports
// app's Dashboard ("#/reports", "#/reports/dashboard").

import { Alert, Result } from 'antd'
import type { ReactNode } from 'react'
import { useCompanies, useHome, usePeriods } from './api/queries.ts'
import { DashboardHome } from './apps/reports/DashboardHome.tsx'
import { useRoute } from './router.ts'
import { chosenPeriod, chosenYear, selectedIds, selectionQuery, useSelection } from './selection.ts'
import { AppShell } from './shell/AppShell.tsx'
import { findApp } from './shell/apps.ts'
import { AppsHome } from './shell/AppsHome.tsx'
import { FilterBar, StatusPill } from './shell/FilterBar.tsx'
import type { Mode } from './theme.ts'

interface Props {
  mode: Mode
  onMode: (mode: Mode) => void
  today: string // YYYY-MM-DD, from the root (tests set it)
  now: Date
}

export default function App({ mode, onMode, today, now }: Props) {
  const route = useRoute()
  const [selection, select] = useSelection()
  const companies = useCompanies()
  const ids = selectedIds(selection, companies.data)
  const periods = usePeriods(ids)
  const year = chosenYear(selection, periods.data)
  const period = chosenPeriod(selection, year, today)
  const app = findApp(route.path[0])
  const page = app ? (route.path[1] ?? app.pages[0].key) : undefined
  const onDashboard = app?.key === 'reports' && page === 'dashboard'
  const home = useHome(onDashboard ? ids : undefined, period, selection.compare)
  const query = selectionQuery(selection)
  const all = companies.data ?? []
  const selected = all.filter((c) => ids?.includes(c.id))

  let content: ReactNode
  if (companies.error) {
    content = <Alert type="error" showIcon message="The dashboard can't reach the data plane." description={companies.error.message} />
  } else if (companies.data && companies.data.length === 0) {
    content = <Alert type="info" showIcon message="No companies to show yet." description="Connect and sync a company first (companies on hold aren't shown)." />
  } else if (route.path.length === 0) {
    content = (
      <AppsHome
        query={query}
        sourceName={all[0]?.health.source_name ?? 'your books'}
        status={<StatusPill companies={all} />}
        now={now}
      />
    )
  } else if (onDashboard) {
    content = (
      <DashboardHome
        companies={selected}
        home={home.data}
        loading={companies.isPending || periods.isPending || home.isPending}
        error={periods.error ?? home.error}
        dark={mode === 'dark'}
      />
    )
  } else {
    content = <Result status="404" title="There is no such page" subTitle="Choose an app from the apps home." />
  }

  const filterBar =
    onDashboard && all.length > 0 ? (
      <FilterBar
        companies={all}
        selection={selection}
        selectedIds={ids ?? []}
        years={periods.data?.financial_years ?? []}
        year={year}
        period={period}
        onChange={select}
      />
    ) : undefined

  return (
    <AppShell app={app} page={page} filterBar={filterBar} query={query} mode={mode} onMode={onMode}>
      {content}
    </AppShell>
  )
}
