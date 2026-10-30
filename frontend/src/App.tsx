// The dashboard: which page the URL asks for, the selection (company, year, "as at"), and
// the shell around the page. Pages: the apps home ("#/"), the Overview ("#/overview").

import { Alert, Result } from 'antd'
import type { ReactNode } from 'react'
import { useCompanies, useOverview, usePeriods } from './api/queries.ts'
import { OverviewApp } from './apps/overview/OverviewApp.tsx'
import { useRoute } from './router.ts'
import { chosenDate, chosenYear, datesInYear, selectedIds, useSelection } from './selection.ts'
import { AppShell, type Crumb } from './shell/AppShell.tsx'
import { findApp } from './shell/apps.ts'
import { AppsHome } from './shell/AppsHome.tsx'
import { CompanySwitcher } from './shell/CompanySwitcher.tsx'
import { PeriodControls } from './shell/PeriodControls.tsx'
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
  const asOf = chosenDate(selection, periods.data, year, today)
  const overview = useOverview(ids, year?.start_year, asOf)

  const app = findApp(route.path[0])
  const query = {
    company: selection.company === 'all' ? undefined : selection.company,
    fy: selection.fy,
    as_of: selection.asOf,
  }
  const home: Crumb = { label: 'Apps', path: [] }
  let crumbs: Crumb[] = [{ label: 'Apps' }]
  let page: ReactNode
  if (route.path.length === 0) {
    page = <AppsHome query={query} />
  } else if (app?.key === 'overview') {
    crumbs = [home, { label: app.title }]
    page = (
      <OverviewApp
        companies={(companies.data ?? []).filter((c) => ids?.includes(c.id))}
        year={year}
        overview={overview.data}
        loading={companies.isPending || periods.isPending || overview.isPending}
        error={companies.error ?? periods.error ?? overview.error}
        dark={mode === 'dark'}
      />
    )
  } else {
    crumbs = [home, { label: 'Not found' }]
    page = <Result status="404" title="There is no such page" subTitle="Choose an app from the apps home." />
  }

  const controls =
    app && companies.data && companies.data.length > 0 ? (
      <>
        <CompanySwitcher companies={companies.data} value={selection.company} onChange={(company) => select({ company, asOf: undefined })} />
        <PeriodControls
          years={periods.data?.financial_years ?? []}
          year={year}
          dates={datesInYear(periods.data, year)}
          asOf={asOf}
          onYear={(fy) => select({ fy, asOf: undefined })}
          onDate={(date) => select({ asOf: date })}
        />
      </>
    ) : null

  return (
    <AppShell app={app} page={route.path[1]} crumbs={crumbs} controls={controls} query={query} mode={mode} onMode={onMode}>
      {companies.error ? (
        <Alert type="error" showIcon message="The dashboard can't reach the data plane." description={companies.error.message} />
      ) : companies.data && companies.data.length === 0 ? (
        <Alert type="info" showIcon message="No companies to show yet." description="Connect and sync a company first (companies on hold aren't shown)." />
      ) : (
        page
      )}
    </AppShell>
  )
}
