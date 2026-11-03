// The dashboard: which page the URL asks for ("#/<module>/<page>", the top bar's modules:
// shell/nav.ts; "#/" is the Overview), the selection (companies, period toggle, year, months or
// dates, comparison, facets) and the page's own options, all in the URL; the top bar and the
// page header around the page (ADR-050).

import { Alert, Result } from 'antd'
import type { ReactNode } from 'react'
import { useAgeing, useChannels, useCompanies, useHome, useMonthly, useParties, useParty, usePeriods, useProfitLoss, usePurchasesDashboard, useRegister, useSalesDashboard } from './api/queries.ts'
import { DashboardHome } from './apps/dashboard/DashboardHome.tsx'
import { PnlKpis } from './apps/dashboard/PnlKpis.tsx'
import { ProfitLoss } from './apps/dashboard/ProfitLoss.tsx'
import { Ageing } from './apps/parties/Ageing.tsx'
import { Parties } from './apps/parties/Parties.tsx'
import { PartyPage, type PartyTab } from './apps/parties/PartyPage.tsx'
import { PARTY_WORDS, type PartyKind } from './apps/parties/words.ts'
import { Monthly } from './apps/registers/Monthly.tsx'
import { Register } from './apps/registers/Register.tsx'
import { Channels } from './apps/sales/Channels.tsx'
import { SalesDashboard } from './apps/sales/SalesDashboard.tsx'
import { readOptions } from './reporting/reportTable.ts'
import { navigate, updateQuery, useRoute } from './router.ts'
import { chosenPeriod, chosenYear, selectedIds, selectionQuery, useSelection } from './selection.ts'
import { AppShell } from './shell/AppShell.tsx'
import { findPage } from './shell/nav.ts'
import { PageHeader, type Crumb } from './shell/PageHeader.tsx'
import { TopBar } from './shell/TopBar.tsx'
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
  const period = chosenPeriod(selection, year, today, periods.data?.financial_years ?? [])
  const found = findPage(route.path)
  const at = found ? `${found.group.key}/${found.page.key}` : undefined
  const home = useHome(at === 'overview/dashboard' || at === 'pnl/profit-loss' ? ids : undefined, period, selection.compare)
  const options = readOptions(route.query)
  const profitLoss = useProfitLoss(at === 'pnl/profit-loss' ? ids : undefined, period, options.view, selection.compare)
  const sales = useSalesDashboard(at === 'sales/dashboard' ? ids : undefined, period, selection.compare, {
    customer: selection.facets.customer,
    channel: selection.facets.channel,
  })
  const purchases = usePurchasesDashboard(at === 'purchases/dashboard' ? ids : undefined, period, selection.compare, selection.facets.voucher_type)
  const ageingKind = at === 'parties/receivables' ? 'customers' : at === 'parties/payables' ? 'vendors' : undefined
  const ageing = useAgeing(ageingKind ?? 'customers', ageingKind ? ids : undefined, period)
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
  const partyKind: PartyKind | undefined = at === 'sales/customers' ? 'customers' : at === 'purchases/vendors' ? 'vendors' : undefined
  const partyId = partyKind && /^\d+$/.test(route.path[2] ?? '') ? route.path[2] : undefined
  const partyList = useParties(partyKind ?? 'customers', partyKind && !partyId ? ids : undefined, period)
  const party = useParty(partyKind ?? 'customers', partyId, partyKind ? ids : undefined, period, selection.compare)
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
    crumbs = [{ label: 'Overview' }]
    content = (
      <DashboardHome home={home.data} loading={companies.isPending || periods.isPending || home.isPending}
        error={periods.error ?? home.error} dark={mode === 'dark'} query={query} />
    )
  } else if (at === 'pnl/profit-loss') {
    crumbs = [{ label: 'P&L & KPIs', path: ['pnl', 'profit-loss'] }, { label: 'Profit & Loss' }]
    content = (
      <>
        <PnlKpis home={home.data} report={profitLoss.data} dark={mode === 'dark'} />
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
          related={[{ label: 'Overview', path: ['overview', 'dashboard'] }]}
        />
      </>
    )
  } else if (at === 'sales/dashboard') {
    crumbs = [{ label: 'Sales', path: ['sales', 'dashboard'] }, { label: 'Sales dashboard' }]
    content = (
      <SalesDashboard
        side="sales"
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
          { label: 'Overview', path: ['overview', 'dashboard'] },
          { label: 'Profit & Loss', path: ['pnl', 'profit-loss'] },
        ]}
      />
    )
  } else if (at === 'purchases/dashboard') {
    crumbs = [{ label: 'Purchases', path: ['purchases', 'dashboard'] }, { label: 'Purchases dashboard' }]
    content = (
      <SalesDashboard
        key="purchases"
        side="purchases"
        companies={selected}
        dashboard={purchases.data}
        loading={companies.isPending || periods.isPending || purchases.isPending}
        error={periods.error ?? purchases.error}
        dark={mode === 'dark'}
        query={query}
        panelOpen={panelOpen}
        onPanel={onPanel}
        currentQuery={route.query.toString()}
        onApplyView={onApplyView}
        related={[
          { label: 'Purchase register', path: ['purchases', 'register'] },
          { label: 'Monthly purchases', path: ['purchases', 'monthly'] },
          { label: 'Sales dashboard', path: ['sales', 'dashboard'] },
        ]}
      />
    )
  } else if (ageingKind) {
    const title = ageingKind === 'customers' ? 'Receivables' : 'Payables'
    crumbs = [{ label: 'Parties', path: ['parties', 'receivables'] }, { label: title }]
    content = (
      <Ageing
        key={ageingKind}
        kind={ageingKind}
        companies={selected}
        ageing={ageing.data}
        loading={companies.isPending || periods.isPending || ageing.isPending}
        error={periods.error ?? ageing.error}
        dark={mode === 'dark'}
        query={query}
        panelOpen={panelOpen}
        onPanel={onPanel}
        currentQuery={route.query.toString()}
        onApplyView={onApplyView}
        related={
          ageingKind === 'customers'
            ? [{ label: 'Customers', path: ['sales', 'customers'] }, { label: 'Payables', path: ['parties', 'payables'] }]
            : [{ label: 'Vendors', path: ['purchases', 'vendors'] }, { label: 'Receivables', path: ['parties', 'receivables'] }]
        }
      />
    )
  } else if (at === 'sales/register' || at === 'purchases/register') {
    const side = at === 'sales/register' ? 'sales' : 'purchases'
    const found = side === 'sales' ? salesRegister : purchaseRegister
    crumbs =
      side === 'sales'
        ? [{ label: 'Sales', path: ['sales', 'dashboard'] }, { label: 'Sales register' }]
        : [{ label: 'Purchases', path: ['purchases', 'dashboard'] }, { label: 'Purchase register' }]
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
                { label: 'Profit & Loss', path: ['pnl', 'profit-loss'] },
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
        : [{ label: 'Purchases', path: ['purchases', 'dashboard'] }, { label: 'Monthly purchases' }]
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
  } else if (partyKind && route.path.length > 2 && !partyId) {
    content = <Result status="404" title="There is no such page" subTitle="Choose a module in the top bar." />
  } else if (partyKind && partyId) {
    const words = PARTY_WORDS[partyKind]
    const [group, list] = words.group
    crumbs = [
      { label: group === 'sales' ? 'Sales' : 'Purchases', path: group === 'sales' ? ['sales', 'dashboard'] : ['purchases', 'register'] },
      { label: words.title, path: [group, list] },
      { label: party.data?.name ?? words.one },
    ]
    const tabs: PartyTab[] = ['invoices', 'settlements', 'statement', 'bills', 'monthly']
    const tab = tabs.find((t) => t === route.query.get('tab')) ?? 'invoices'
    content = (
      <PartyPage
        key={partyId}
        kind={partyKind}
        companies={selected}
        party={party.data}
        loading={companies.isPending || periods.isPending || party.isPending}
        error={periods.error ?? party.error}
        dark={mode === 'dark'}
        tab={tab}
        onTab={(next) => updateQuery(route, { tab: next === 'invoices' ? undefined : next })}
        query={query}
        panelOpen={panelOpen}
        onPanel={onPanel}
        currentQuery={route.query.toString()}
        onApplyView={onApplyView}
        related={[
          { label: words.title, path: [group, list] },
          { label: group === 'sales' ? 'Sales register' : 'Purchase register', path: words.register },
        ]}
      />
    )
  } else if (partyKind) {
    const words = PARTY_WORDS[partyKind]
    const [group] = words.group
    crumbs = [
      { label: group === 'sales' ? 'Sales' : 'Purchases', path: group === 'sales' ? ['sales', 'dashboard'] : ['purchases', 'register'] },
      { label: words.title },
    ]
    content = (
      <Parties
        key={partyKind}
        kind={partyKind}
        companies={selected}
        parties={partyList.data}
        loading={companies.isPending || periods.isPending || partyList.isPending}
        error={periods.error ?? partyList.error}
        query={query}
        panelOpen={panelOpen}
        onPanel={onPanel}
        currentQuery={route.query.toString()}
        onApplyView={onApplyView}
        related={[{ label: group === 'sales' ? 'Sales register' : 'Purchase register', path: words.register }]}
      />
    )
  } else {
    content = <Result status="404" title="There is no such page" subTitle="Choose a module in the top bar." />
  }

  return (
    <AppShell
      topBar={
        <TopBar module={found?.group.key} query={query} selection={selection} years={periods.data?.financial_years ?? []} year={year}
          period={period} onChange={select} mode={mode} onMode={onMode} />
      }
      header={
        <PageHeader crumbs={crumbs} title={crumbs[crumbs.length - 1].label} group={found?.group} page={found?.page} companies={all}
          selection={selection} selectedIds={ids ?? []} period={period} onChange={select} query={query} />
      }
    >
      {content}
    </AppShell>
  )
}
