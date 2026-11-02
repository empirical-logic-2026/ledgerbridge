// The dashboard: which page the URL asks for ("#/<group>/<page>", the side bar's groups:
// shell/nav.ts; "#/" is the Dashboard), the selection (companies, year, months or dates,
// compare, facets) and the page's own options, all in the URL; the side bar and the top filter
// bar around the page.

import { Alert, Result } from 'antd'
import type { ReactNode } from 'react'
import { useChannels, useCompanies, useHome, useMonthly, usePeriods, useProfitLoss, useRegister, useSalesDashboard } from './api/queries.ts'
import { DashboardHome } from './apps/dashboard/DashboardHome.tsx'
import { ProfitLoss } from './apps/dashboard/ProfitLoss.tsx'
import { Monthly } from './apps/registers/Monthly.tsx'
import { Register } from './apps/registers/Register.tsx'
import { Channels } from './apps/sales/Channels.tsx'
import { SalesDashboard } from './apps/sales/SalesDashboard.tsx'
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
  const sales = useSalesDashboard(at === 'sales/dashboard' ? ids : undefined, period, selection.compare, {
    customer: selection.facets.customer,
    channel: selection.facets.channel,
  })
  const salesRegister = useRegister('sales', at === 'sales/register' ? ids : undefined, period, {
    party: selection.facets.customer,
    voucherType: selection.facets.channel,
  })
  const purchaseRegister = useRegister('purchases', at === 'purchases/register' ? ids : undefined, period, {
    party: [],
    voucherType: selection.facets.voucher_type,
  })
  const monthlySales = useMonthly('sales', at === 'sales/monthly' ? ids : undefined, period, {
    party: selection.facets.customer,
    voucherType: selection.facets.channel,
  })
  const monthlyPurchases = useMonthly('purchases', at === 'purchases/monthly' ? ids : undefined, period, {
    party: [],
    voucherType: selection.facets.voucher_type,
  })
  const channels = useChannels(at === 'sales/channels' ? ids : undefined, period, {
    customer: selection.facets.customer,
    channel: selection.facets.channel,
  })
  const query = selectionQuery(selection)
  const panelOpen = route.query.get('panel') !== '0'
  const onPanel = (open: boolean) => updateQuery(route, { panel: open ? undefined : '0' })
  const onApplyView = (saved: string) => navigate(route.path, Object.fromEntries(new URLSearchParams(saved)))
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
        panelOpen={panelOpen}
        onPanel={onPanel}
        query={query}
        currentQuery={route.query.toString()}
        onApplyView={onApplyView}
        related={[{ label: 'Dashboard', path: ['overview', 'dashboard'] }]}
      />
    )
  } else if (at === 'sales/dashboard') {
    crumbs = [{ label: 'Sales', path: ['sales', 'dashboard'] }, { label: 'Sales dashboard' }]
    content = (
      <SalesDashboard
        companies={selected}
        dashboard={sales.data}
        loading={companies.isPending || periods.isPending || sales.isPending}
        error={periods.error ?? sales.error}
        dark={mode === 'dark'}
        query={query}
        panelOpen={panelOpen}
        onPanel={onPanel}
        currentQuery={route.query.toString()}
        onApplyView={onApplyView}
        related={[
          { label: 'Sales register', path: ['sales', 'register'] },
          { label: 'Dashboard', path: ['overview', 'dashboard'] },
          { label: 'Profit & Loss', path: ['statements', 'profit-loss'] },
        ]}
      />
    )
  } else if (at === 'sales/register' || at === 'purchases/register') {
    const side = at === 'sales/register' ? 'sales' : 'purchases'
    const found = side === 'sales' ? salesRegister : purchaseRegister
    crumbs =
      side === 'sales'
        ? [{ label: 'Sales', path: ['sales', 'dashboard'] }, { label: 'Sales register' }]
        : [{ label: 'Purchases', path: ['purchases', 'register'] }, { label: 'Purchase register' }]
    content = (
      <Register
        key={side}
        side={side}
        companies={selected}
        register={found.data}
        loading={companies.isPending || periods.isPending || found.isPending}
        error={periods.error ?? found.error}
        query={query}
        panelOpen={panelOpen}
        onPanel={onPanel}
        currentQuery={route.query.toString()}
        onApplyView={onApplyView}
        related={
          side === 'sales'
            ? [
                { label: 'Sales dashboard', path: ['sales', 'dashboard'] },
                { label: 'Purchase register', path: ['purchases', 'register'] },
              ]
            : [
                { label: 'Sales register', path: ['sales', 'register'] },
                { label: 'Profit & Loss', path: ['statements', 'profit-loss'] },
              ]
        }
      />
    )
  } else if (at === 'sales/monthly' || at === 'purchases/monthly') {
    const side = at === 'sales/monthly' ? 'sales' : 'purchases'
    const found = side === 'sales' ? monthlySales : monthlyPurchases
    crumbs =
      side === 'sales'
        ? [{ label: 'Sales', path: ['sales', 'dashboard'] }, { label: 'Monthly sales' }]
        : [{ label: 'Purchases', path: ['purchases', 'register'] }, { label: 'Monthly purchases' }]
    content = (
      <Monthly
        key={side}
        side={side}
        companies={selected}
        monthly={found.data}
        loading={companies.isPending || periods.isPending || found.isPending}
        error={periods.error ?? found.error}
        dark={mode === 'dark'}
        query={query}
        panelOpen={panelOpen}
        onPanel={onPanel}
        currentQuery={route.query.toString()}
        onApplyView={onApplyView}
        related={
          side === 'sales'
            ? [
                { label: 'Sales register', path: ['sales', 'register'] },
                { label: 'Sales by channel', path: ['sales', 'channels'] },
                { label: 'Monthly purchases', path: ['purchases', 'monthly'] },
              ]
            : [
                { label: 'Purchase register', path: ['purchases', 'register'] },
                { label: 'Monthly sales', path: ['sales', 'monthly'] },
              ]
        }
      />
    )
  } else if (at === 'sales/channels') {
    crumbs = [{ label: 'Sales', path: ['sales', 'dashboard'] }, { label: 'Channels' }]
    content = (
      <Channels
        companies={selected}
        channels={channels.data}
        loading={companies.isPending || periods.isPending || channels.isPending}
        error={periods.error ?? channels.error}
        dark={mode === 'dark'}
        query={query}
        panelOpen={panelOpen}
        onPanel={onPanel}
        currentQuery={route.query.toString()}
        onApplyView={onApplyView}
        related={[
          { label: 'Sales dashboard', path: ['sales', 'dashboard'] },
          { label: 'Monthly sales', path: ['sales', 'monthly'] },
          { label: 'Sales register', path: ['sales', 'register'] },
        ]}
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
