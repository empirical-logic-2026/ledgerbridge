// The dashboard: which page the URL asks for ("#/<module>/<page>", the top bar's modules:
// shell/nav.ts; "#/" is the Overview), the selection (companies, period toggle, year, months or
// dates, comparison, facets) and the page's own options, all in the URL; the top bar and the
// page header around the page (ADR-050).

import { AmountFormatProvider } from './components/Money.tsx'
import { Alert, Result } from 'antd'
import type { ReactNode } from 'react'
import { useAgeing, useBalanceSheet, useCashFlow, useChannels, useCompanies, useCostCentre, useCostCentres, useHome, useStock, useStockGodowns, useStockItem, useTransactions, useVoucher, useMonthly, useParties, useParty, usePeriods, useProfitLoss, usePurchasesDashboard, useRegister, useSalesDashboard } from './api/queries.ts'
import { ErrorState } from './components/loading/ErrorState.tsx'
import { Loading } from './components/loading/Loading.tsx'
import { DashboardHome } from './apps/dashboard/DashboardHome.tsx'
import { PnlKpis } from './apps/dashboard/PnlKpis.tsx'
import { ProfitLoss } from './apps/dashboard/ProfitLoss.tsx'
import { CostCentrePage, CostCentres } from './apps/costcentres/CostCentres.tsx'
import { StockItemPage, StockSummary } from './apps/stock/Stock.tsx'
import { StockGodowns } from './apps/stock/StockGodowns.tsx'
import { Transactions } from './apps/books/Transactions.tsx'
import { VoucherPage } from './apps/books/VoucherPage.tsx'
import { Explore } from './apps/data/Explore.tsx'
import { Ageing } from './apps/parties/Ageing.tsx'
import { BalanceSheet } from './apps/statements/BalanceSheet.tsx'
import { CashFlow } from './apps/cash/CashFlow.tsx'
import { CompaniesPage, DataHealth } from './apps/data/DataPages.tsx'
import { Parties } from './apps/parties/Parties.tsx'
import { PartyPage, type PartyTab } from './apps/parties/PartyPage.tsx'
import { PARTY_WORDS, type PartyKind } from './apps/parties/words.ts'
import { Monthly } from './apps/registers/Monthly.tsx'
import { Register } from './apps/registers/Register.tsx'
import { Channels } from './apps/sales/Channels.tsx'
import { SalesDashboard } from './apps/sales/SalesDashboard.tsx'
import { readOptions } from './reporting/reportTable.ts'
import { updateQuery, useRoute } from './router.ts'
import { chosenPeriod, chosenYear, periodDates, selectedIds, selectionQuery, useSelection } from './selection.ts'
import { AppShell } from './shell/AppShell.tsx'
import { findPage } from './shell/nav.ts'
import { pageNoteFor } from './shell/pageNotes.ts'
import { PageNote } from './components/PageNote.tsx'
import { PageHeader, type Crumb } from './shell/PageHeader.tsx'
import { TopBar } from './shell/TopBar.tsx'
import type { Mode } from './theme.ts'

interface Props {
  mode: Mode
  onMode: (mode: Mode) => void
  today: string // YYYY-MM-DD, from the root (tests set it)
}

/** A request that can be asked again: a TanStack query's error and refetch. */
interface Refetchable {
  error: Error | null
  refetch: () => unknown
}

/** Retry for an error state: asks again for each request that failed (the periods before the
 *  page's own figures, which wait for them). */
function retry(...queries: Refetchable[]): () => void {
  return () => {
    for (const query of queries) if (query.error) void query.refetch()
  }
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
  const ageingBasis = route.query.get('basis') === 'bill_date' ? 'bill_date' : 'due_date'
  const ageing = useAgeing(ageingKind ?? 'customers', ageingKind ? ids : undefined, period, ageingBasis)
  const sheet = useBalanceSheet(at === 'balance-sheet/statement' ? ids : undefined, period, selection.compare)
  const flow = useCashFlow(at === 'cash-flow/movement' ? ids : undefined, period)
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
  const centreId = at === 'pnl/cost-centres' && /^\d+$/.test(route.path[2] ?? '') ? route.path[2] : undefined
  const centreList = useCostCentres(at === 'pnl/cost-centres' && route.path.length < 3 ? ids : undefined, period)
  const centre = useCostCentre(centreId, at === 'pnl/cost-centres' ? ids : undefined, period)
  const stockItemId = at === 'stock/summary' && /^\d+$/.test(route.path[2] ?? '') ? route.path[2] : undefined
  const stock = useStock(at === 'stock/summary' && route.path.length < 3 ? ids : undefined, period)
  const stockGodown = route.query.get('godown') ?? undefined
  const stockItem = useStockItem(stockItemId, at === 'stock/summary' ? ids : undefined, period, stockGodown)
  const stockGodowns = useStockGodowns(at === 'stock/godowns' ? ids : undefined, period)
  const transactions = useTransactions(at === 'books/transactions' ? ids : undefined, period)
  const voucherId = at === 'books/vouchers' && /^\d+$/.test(route.path[2] ?? '') ? route.path[2] : undefined
  const voucher = useVoucher(voucherId, at === 'books/vouchers' ? ids : undefined)
  const query = selectionQuery(selection)
  const all = companies.data ?? []
  const selected = all.filter((c) => ids?.includes(c.id))

  let crumbs: Crumb[] = [{ label: 'There is no such page' }]
  let content: ReactNode
  if (companies.error) {
    content = <ErrorState message="The dashboard can't reach the data plane." error={companies.error} onRetry={retry(companies)} />
  } else if (companies.data && companies.data.length === 0) {
    content = <Alert type="info" showIcon message="No companies to show yet." description="Connect and sync a company first (companies on hold aren't shown)." />
  } else if (at === 'overview/dashboard') {
    crumbs = [{ label: 'Overview' }]
    content = (
      <DashboardHome home={home.data} loading={companies.isPending || periods.isPending || home.isPending}
        error={periods.error ?? home.error}
        onRetry={retry(periods, home)} dark={mode === 'dark'} query={query} />
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
        onRetry={retry(periods, profitLoss)}
          options={options}
          onOptions={(change) => updateQuery(route, change)}
              query={query}
        />
      </>
    )
  } else if (at === 'pnl/cost-centres' && route.path.length > 2 && !centreId) {
    content = <Result status="404" title="There is no such page" subTitle="Choose a module in the top bar." />
  } else if (at === 'pnl/cost-centres' && centreId) {
    crumbs = [{ label: 'P&L & KPIs', path: ['pnl', 'profit-loss'] }, { label: 'Cost centres', path: ['pnl', 'cost-centres'] }, { label: centre.data?.centre.name ?? 'Cost centre' }]
    content = (
      <CostCentrePage
        key={centreId}
        companies={selected}
        centre={centre.data}
        loading={companies.isPending || periods.isPending || centre.isPending}
        error={periods.error ?? centre.error}
        onRetry={retry(periods, centre)}
        query={query}
      />
    )
  } else if (at === 'pnl/cost-centres') {
    crumbs = [{ label: 'P&L & KPIs', path: ['pnl', 'profit-loss'] }, { label: 'Cost centres' }]
    content = (
      <CostCentres
        companies={selected}
        centres={centreList.data}
        loading={companies.isPending || periods.isPending || centreList.isPending}
        error={periods.error ?? centreList.error}
        onRetry={retry(periods, centreList)}
        query={query}
      />
    )
  } else if (at === 'books/vouchers' && !voucherId) {
    content = <Result status="404" title="There is no such page" subTitle="Open a voucher from a register, a table or a bill." />
  } else if (at === 'books/vouchers') {
    crumbs = [{ label: 'Books', path: ['books', 'transactions'] }, { label: voucher.data ? `${voucher.data.voucher_type} ${voucher.data.number}` : 'Voucher' }]
    content = (
      <VoucherPage
        key={voucherId}
        companies={selected}
        voucher={voucher.data}
        loading={companies.isPending || voucher.isPending}
        error={voucher.error}
        onRetry={retry(voucher)}
        query={query}
      />
    )
  } else if (at === 'data/explore') {
    crumbs = [{ label: 'Data', path: ['data', 'health'] }, { label: 'Explore' }]
    const [from, to] = period ? periodDates(period) : [undefined, undefined]
    content = companies.isPending ? (
      <Loading shape="report" />
    ) : (
      <Explore companies={selected} companyIds={ids ?? []} period={from && to ? { from, to } : undefined} query={query} />
    )
  } else if (at === 'books/transactions') {
    crumbs = [{ label: 'Books', path: ['books', 'transactions'] }, { label: 'Transactions' }]
    content = (
      <Transactions
        companies={selected}
        page={transactions.data}
        loading={companies.isPending || periods.isPending || transactions.isPending}
        error={periods.error ?? transactions.error}
        onRetry={retry(periods, transactions)}
        query={query}
      />
    )
  } else if (at === 'stock/summary' && route.path.length > 2 && !stockItemId) {
    content = <Result status="404" title="There is no such page" subTitle="Choose a module in the top bar." />
  } else if (at === 'stock/summary' && stockItemId) {
    crumbs = [{ label: 'Stock', path: ['stock', 'summary'] }, { label: 'Stock summary', path: ['stock', 'summary'] }, { label: stockItem.data?.item.name ?? 'Stock item' }]
    content = (
      <StockItemPage
        key={stockItemId}
        companies={selected}
        page={stockItem.data}
        loading={companies.isPending || periods.isPending || stockItem.isPending}
        error={periods.error ?? stockItem.error}
        onRetry={retry(periods, stockItem)}
        dark={mode === 'dark'}
        query={query}
      />
    )
  } else if (at === 'stock/godowns') {
    crumbs = [{ label: 'Stock', path: ['stock', 'summary'] }, { label: 'By godown' }]
    content = (
      <StockGodowns
        companies={selected}
        found={stockGodowns.data}
        loading={companies.isPending || periods.isPending || stockGodowns.isPending}
        error={periods.error ?? stockGodowns.error}
        onRetry={retry(periods, stockGodowns)}
        dark={mode === 'dark'}
        query={query}
      />
    )
  } else if (at === 'stock/summary') {
    crumbs = [{ label: 'Stock', path: ['stock', 'summary'] }, { label: 'Stock summary' }]
    content = (
      <StockSummary
        companies={selected}
        stock={stock.data}
        loading={companies.isPending || periods.isPending || stock.isPending}
        error={periods.error ?? stock.error}
        onRetry={retry(periods, stock)}
        dark={mode === 'dark'}
        query={query}
      />
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
        onRetry={retry(periods, sales)}
        dark={mode === 'dark'}
        query={query}
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
        onRetry={retry(periods, purchases)}
        dark={mode === 'dark'}
        query={query}
      />
    )
  } else if (at === 'balance-sheet/statement') {
    crumbs = [{ label: 'Balance Sheet' }]
    content = (
      <BalanceSheet
        companies={selected}
        sheet={sheet.data}
        loading={companies.isPending || periods.isPending || sheet.isPending}
        error={periods.error ?? sheet.error}
        onRetry={retry(periods, sheet)}
        query={query}
      />
    )
  } else if (at === 'data/health') {
    crumbs = [{ label: 'Data', path: ['data', 'health'] }, { label: 'Data health' }]
    content = companies.isPending ? <Loading shape="dashboard" /> : <DataHealth companies={all} dark={mode === 'dark'} />
  } else if (at === 'data/companies') {
    crumbs = [{ label: 'Data', path: ['data', 'health'] }, { label: 'Companies' }]
    content = companies.isPending ? <Loading shape="report" /> : <CompaniesPage companies={all} />
  } else if (at === 'cash-flow/movement') {
    crumbs = [{ label: 'Cash Flow' }]
    content = (
      <CashFlow
        companies={selected}
        flow={flow.data}
        loading={companies.isPending || periods.isPending || flow.isPending}
        error={periods.error ?? flow.error}
        onRetry={retry(periods, flow)}
        dark={mode === 'dark'}
        query={query}
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
        onRetry={retry(periods, ageing)}
        dark={mode === 'dark'}
        query={query}
        basis={ageingBasis}
        onBasis={(basis) => updateQuery(route, { basis: basis === 'due_date' ? undefined : basis })}
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
        onRetry={retry(periods, found)}
        query={query}
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
        onRetry={retry(periods, found)}
        dark={mode === 'dark'}
        query={query}
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
        onRetry={retry(periods, channels)}
        dark={mode === 'dark'}
        query={query}
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
        onRetry={retry(periods, party)}
        dark={mode === 'dark'}
        tab={tab}
        onTab={(next) => updateQuery(route, { tab: next === 'invoices' ? undefined : next })}
        query={query}
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
        onRetry={retry(periods, partyList)}
        query={query}
      />
    )
  } else {
    content = <Result status="404" title="There is no such page" subTitle="Choose a module in the top bar." />
  }

  // The page's note at its top (shell/pageNotes.ts): not for an address with a bad id, nor when
  // there is nothing to show (no companies, or the data plane unreachable).
  const rowId = route.path[2]
  const pageIsThere = found !== undefined && (rowId === undefined || /^\d+$/.test(rowId)) && route.path.length <= 3
  const hasData = !companies.error && !(companies.data && companies.data.length === 0)
  const note = pageIsThere && hasData && at ? pageNoteFor(at, rowId !== undefined) : undefined

  return (
    <AmountFormatProvider>
      <AppShell
        topBar={
          <TopBar module={found?.group.key} starting={companies.isLoading || periods.isLoading} query={query} selection={selection} years={periods.data?.financial_years ?? []} year={year}
            period={period} onChange={select} mode={mode} onMode={onMode} />
        }
        header={
          <PageHeader crumbs={crumbs} title={crumbs[crumbs.length - 1].label} group={found?.group} page={found?.page} companies={all}
            selection={selection} selectedIds={ids ?? []} period={period} onChange={select} query={query} />
        }
      >
        {note && <PageNote key={note.page} page={note.page} note={note.note} pageTitle={crumbs[crumbs.length - 1].label} />}
        {content}
      </AppShell>
    </AmountFormatProvider>
  )
}
