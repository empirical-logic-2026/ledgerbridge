// The dashboard: which page the URL asks for ("#/<group>/<page>", the side bar's groups:
// shell/nav.ts; "#/" is the Dashboard), the selection (companies, year, months or dates,
// compare, facets) and the page's own options, all in the URL; the side bar and the top filter
// bar around the page.

import { Alert, Result } from 'antd'
import type { ReactNode } from 'react'
import { useCompanies, useHome, usePeriods, useProfitLoss } from './api/queries.ts'
import { DashboardHome } from './apps/dashboard/DashboardHome.tsx'
import { ProfitLoss } from './apps/dashboard/ProfitLoss.tsx'
import { readOptions } from './reporting/reportTable.ts'
import { navigate, updateQuery, useRoute } from './router.ts'
import { chosenPeriod, chosenYear, selectedIds, selectionQuery, useSelection } from './selection.ts'
import { AppShell } from './shell/AppShell.tsx'
import { findPage } from './shell/nav.ts'
import { SideBar } from './shell/SideBar.tsx'
import { TopBar, type Crumb } from './shell/TopBar.tsx'
import type { Mode } from './theme.ts'

interface Props {
  mode: Mode
  onMode: (mode: Mode) => void
  today: string // YYYY-MM-DD, from the root (tests set it)
}

export default function App({ mode, onMode, today }: Props) {
  const route = useRoute()
  const [selection, select] = useSelection()
  const companies = useCompanies()
  const ids = selectedIds(selection, companies.data)
  const periods = usePeriods(ids)
  const year = chosenYear(selection, periods.data)
  const period = chosenPeriod(selection, year, today)
  const found = findPage(route.path)
  const at = found ? `${found.group.key}/${found.page.key}` : undefined
  const home = useHome(at === 'overview/dashboard' ? ids : undefined, period, selection.compare)
  const options = readOptions(route.query)
  const profitLoss = useProfitLoss(at === 'statements/profit-loss' ? ids : undefined, period, options.view, selection.compare)
  const query = selectionQuery(selection)
  const all = companies.data ?? []
  const selected = all.filter((c) => ids?.includes(c.id))

  let crumbs: Crumb[] = [{ label: 'There is no such page' }]
  let content: ReactNode
  if (companies.error) {
    content = <Alert type="error" showIcon message="The dashboard can't reach the data plane." description={companies.error.message} />
  } else if (companies.data && companies.data.length === 0) {
    content = <Alert type="info" showIcon message="No companies to show yet." description="Connect and sync a company first (companies on hold aren't shown)." />
  } else if (at === 'overview/dashboard') {
    crumbs = [{ label: 'Overview', path: ['overview', 'dashboard'] }, { label: 'Dashboard' }]
    content = (
      <DashboardHome companies={selected} home={home.data} loading={companies.isPending || periods.isPending || home.isPending}
        error={periods.error ?? home.error} dark={mode === 'dark'} query={query} />
    )
  } else if (at === 'statements/profit-loss') {
    crumbs = [{ label: 'Statements', path: ['statements', 'profit-loss'] }, { label: 'Profit & Loss' }]
    content = (
      <ProfitLoss
        companies={selected}
        report={profitLoss.data}
        loading={companies.isPending || periods.isPending || profitLoss.isPending}
        error={periods.error ?? profitLoss.error}
        options={options}
        onOptions={(change) => updateQuery(route, change)}
        panelOpen={route.query.get('panel') !== '0'}
        onPanel={(open) => updateQuery(route, { panel: open ? undefined : '0' })}
        query={query}
        currentQuery={route.query.toString()}
        onApplyView={(saved) => navigate(route.path, Object.fromEntries(new URLSearchParams(saved)))}
        related={[{ label: 'Dashboard', path: ['overview', 'dashboard'] }]}
      />
    )
  } else {
    content = <Result status="404" title="There is no such page" subTitle="Choose a page in the side bar." />
  }

  return (
    <AppShell
      sideBar={(collapsed, onCollapse) => (
        <SideBar current={found ? [found.group.key, found.page.key] : undefined} query={query} companies={all} mode={mode} onMode={onMode}
          collapsed={collapsed} onCollapse={onCollapse} />
      )}
      topBar={
        <TopBar crumbs={crumbs} page={found?.page} companies={all} selection={selection} selectedIds={ids ?? []}
          years={periods.data?.financial_years ?? []} year={year} period={period} onChange={select} query={query} />
      }
    >
      {content}
    </AppShell>
  )
}
