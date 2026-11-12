// The Sales dashboard (docs/design/dashboard.md Sections 0.2 and 0.4, screen 7), in the
// reference pattern: key cards with the change against the comparison period and the period's
// months as a sparkline (net sales, invoices, average invoice, sales returns), net sales by
// month (a month opens its register; a table below gives every month's gross, returns, other
// adjustments and net), the mix by channel as a donut (a channel opens its register), the top
// customers with their status and the largest invoices, each table in the table explorer; the
// options side panel with "What is this?". Figures: core/sales.py (GET /api/v1/sales/dashboard).
// The same page for purchases (`side`): net purchases, the vendors and the mix by voucher type
// (GET /api/v1/purchases/dashboard); its words: words.ts.

import { Typography } from 'antd'
import { ErrorState } from '../../components/loading/ErrorState.tsx'
import { Loading } from '../../components/loading/Loading.tsx'
import type { EChartsOption } from 'echarts'
import type { Company, InvoiceOut, MonthSales, PartySales, SalesDashboard as Dashboard } from '../../api/types.ts'
import { branchSalesChart } from './branchSalesChart.ts'
import { Donut } from '../../components/Donut.tsx'
import { EChart } from '../../components/EChart.tsx'
import { KeyCard } from '../../components/KeyCard.tsx'
import { againstOf } from '../../selection.ts'
import { formatExact, formatMonth, toLakhs, toScaled } from '../../format.ts'
import type { ExplorerColumn } from '../../reporting/explorer.ts'
import { ExplorerTable } from '../../reporting/ExplorerTable.tsx'
import { WhatIsThis } from '../../reporting/WhatIsThis.tsx'
import type { Query } from '../../router.ts'
import { builtHref } from '../../shell/nav.ts'
import { tokens, type Tokens } from '../../theme.ts'
import { COMBINED_NOTE } from '../dashboard/words.ts'
import { SIDE_WORDS, type Side, type SideWords } from './words.ts'
import { companyDisplayName } from '../../companyDisplayName.ts'
import { partyPaymentStatusInfo, statusHint } from '../../statuses.ts'

interface Props {
  side: Side
  companies: Company[] // the selected ones
  dashboard: Dashboard | undefined
  loading: boolean
  error: Error | null
  onRetry?: () => void // ask again after an error
  dark: boolean
  query: Query // the selection, kept on every link
}

function monthChart(months: MonthSales[], colours: Tokens, w: SideWords): EChartsOption {
  const text = colours.muted
  return {
    backgroundColor: 'transparent',
    grid: { left: 48, right: 12, top: 16, bottom: 28 },
    tooltip: {
      trigger: 'axis',
      formatter: (params: unknown) => {
        const [first] = params as { dataIndex: number }[]
        const m = months[first.dataIndex]
        return `${formatMonth(m.month)}<br/>${w.net} ${formatExact(m.net)}<br/>Invoices ${m.invoices}`
      },
    },
    xAxis: { type: 'category', data: months.map((m) => formatMonth(m.month).slice(0, 3)), axisLabel: { color: text } },
    yAxis: { type: 'value', axisLabel: { color: text }, splitLine: { lineStyle: { color: colours.border } } },
    series: [
      {
        type: 'line',
        name: w.net,
        data: months.map((m) => toLakhs(m.net)),
        itemStyle: { color: colours.primary },
        lineStyle: { color: colours.primary, width: 2 },
        symbolSize: 8,
        areaStyle: { color: colours.primarySoft, opacity: 0.6 },
      },
    ],
  }
}

/** The page a month opens: its register once built, else this page for that month (Custom). */
function monthHref(month: string, query: Query, w: SideWords): string {
  const one = { ...query, p: 'custom', month: month.slice(0, 7), from: undefined, to: undefined }
  return builtHref([w.module, 'register'], one) ?? builtHref([w.module, 'dashboard'], one) ?? '#'
}

/** A customer (vendor) opens their page once built, else this page (for sales, filtered to them). */
function partyHref(p: { party_id: number | null; name: string | null }, query: Query, w: SideWords): string | undefined {
  if (p.party_id === null || !p.name) return undefined
  const filtered = w.module === 'sales' ? { ...query, customer: [p.name] } : query
  return builtHref([w.module, w.parties, String(p.party_id)], query) ?? builtHref([w.module, 'dashboard'], filtered)
}

function monthColumns(query: Query, w: SideWords): ExplorerColumn<MonthSales>[] {
  return [
    { key: 'month', label: 'Month', kind: 'text', value: (m) => formatMonth(m.month), link: (m) => monthHref(m.month, query, w) },
    { key: 'gross', label: 'Gross', kind: 'amount', value: (m) => m.gross },
    { key: 'returns', label: 'Returns', kind: 'amount', value: (m) => m.returns },
    { key: 'other', label: 'Other adjustments', kind: 'amount', value: (m) => m.other },
    { key: 'net', label: w.net, kind: 'amount', value: (m) => m.net, link: (m) => monthHref(m.month, query, w) },
    { key: 'invoices', label: 'Invoices', kind: 'count', value: (m) => m.invoices },
  ]
}

function customerColumns(names: Map<number, string>, combined: boolean, query: Query, total: string, w: SideWords): ExplorerColumn<PartySales>[] {
  const share = (net: string) => {
    const all = toScaled(total)
    return all > 0n ? `${(Number((toScaled(net) * 1000n) / all) / 10).toFixed(1)}%` : null
  }
  const kind = w.module === 'sales' ? 'customers' : 'vendors'
  return [
    { key: 'name', label: w.party, kind: 'text', value: (p) => p.name, link: (p) => partyHref({ party_id: p.party_id, name: p.name }, query, w),
      help: "Hover a row's name to see its payment status and what it means.", hint: (p) => statusHint(partyPaymentStatusInfo(p.payment_status ?? p.status, p.balance, kind)) },
    { key: 'company', label: 'Company', kind: 'text', value: (p) => names.get(p.company) ?? `Company ${p.company}`, groupable: true, hidden: !combined },
    { key: 'net', label: w.net, kind: 'amount', value: (p) => p.net_sales },
    { key: 'share', label: 'Share', kind: 'text', value: (p) => share(p.net_sales) },
    { key: 'invoices', label: 'Invoices', kind: 'count', value: (p) => p.invoices },
    { key: 'balance', label: 'Balance due', kind: 'amount', value: (p) => p.balance, summed: false },
  ]
}

/** A month's average invoice, for the sparkline only (gross ÷ invoices). */
function average(m: MonthSales): number | null {
  return m.invoices ? toLakhs(m.gross) / m.invoices : null
}

function invoiceColumns(names: Map<number, string>, combined: boolean, query: Query, w: SideWords): ExplorerColumn<InvoiceOut>[] {
  return [
    { key: 'date', label: 'Date', kind: 'date', value: (i) => i.date },
    { key: 'number', label: 'Vch No.', kind: 'text', value: (i) => i.number, link: (i) => builtHref(['books', 'vouchers', String(i.voucher_id)], query) },
    { key: 'type', label: 'Vch Type', kind: 'text', value: (i) => i.voucher_type, groupable: true },
    { key: 'party', label: w.party, kind: 'text', value: (i) => i.party, link: (i) => partyHref({ party_id: i.party_id, name: i.party }, query, w), groupable: true },
    { key: 'company', label: 'Company', kind: 'text', value: (i) => names.get(i.company) ?? `Company ${i.company}`, groupable: true, hidden: !combined },
    { key: 'amount', label: 'Amount', kind: 'amount', value: (i) => i.amount },
  ]
}

function PurchasesHelp({ sourceName }: { sourceName: string }) {
  return (
    <>
      <p>
        Purchases of the companies, period and voucher types you chose. <strong>Net purchases</strong> are the entries on the ledgers under
        {' '}{sourceName}'s Purchase Accounts group: invoices (gross), less returns (debit notes), plus or minus other adjustments.
      </p>
      <p>
        <strong>Where the figures come from:</strong> the books, rebuilt after every sync; the same definitions as the sales (formulas F-SAL-001 to
        F-SAL-007 on the purchase side). Several companies are added together without inter-company eliminations.
      </p>
      <p>
        <strong>To compare with {sourceName}:</strong> net purchases are the Purchase Accounts line of its Profit &amp; Loss for the same period;
        gross purchases and invoices are its Purchase Register, and returns its Debit Note Register.
      </p>
    </>
  )
}

function Help({ sourceName }: { sourceName: string }) {
  return (
    <>
      <p>
        Sales of the companies, period, customers and channels you chose. <strong>Net sales</strong> are the entries on the ledgers under {sourceName}'s
        Sales Accounts group: invoices (gross), less returns (credit notes), plus or minus other adjustments (journals and the like).
      </p>
      <p>
        <strong>Invoices</strong> are the sales vouchers with an entry on those ledgers; the <strong>average invoice</strong> is gross sales divided by
        them. <strong>Sales returns</strong> are the credit notes on those ledgers. The change compares the same months (or dates) last year.
      </p>
      <p>
        <strong>Where the figures come from:</strong> the books, rebuilt after every sync. Month by month they are the same figures as the monthly
        sales check, which proves every day against {sourceName}'s own statements (<code>./dev.ps1 validate monthly-sales</code>). Several companies are
        added together without inter-company eliminations.
      </p>
      <p>
        <strong>To compare with {sourceName}:</strong> net sales are the Sales Accounts line of its Profit &amp; Loss for the same period; gross sales
        and invoices are its Sales Register (Display More Reports → Account Books) for the same months, and returns its Credit Note Register.
      </p>
    </>
  )
}

export function SalesDashboard(props: Props) {
  const { dashboard, companies, query } = props
  const w = SIDE_WORDS[props.side]
  const sourceName = companies[0]?.health.source_name ?? 'the source'
  const names = new Map(companies.map((c) => [c.id, companyDisplayName(c)]))
  const colours = tokens[props.dark ? 'dark' : 'light']

  let content: React.ReactNode
  if (props.error) {
    content = <ErrorState message={w.loadError} error={props.error} onRetry={props.onRetry} />
  } else if (props.loading || !dashboard) {
    content = <Loading shape="dashboard" />
  } else {
    const k = dashboard.key_figures
    const combined = dashboard.combined
    const net = k.net_sales.value ?? '0'
    const against = againstOf(dashboard.compared_with)
    const [green, charcoal, lighter, grey] = colours.accents
    const register = (part: string) => (part === 'Others' ? undefined : builtHref([w.module, 'register'], { ...query, [w.facet === 'channel' ? 'channel' : 'vtype']: [part] }))
    content = (
      <>
        <div className="sales-cards">
          <KeyCard label={w.net} figure={k.net_sales} tone="up-good" against={against} accent={green}
            spark={dashboard.monthly.map((m) => toLakhs(m.net))} />
          <KeyCard label="Invoices" figure={k.invoices} unit="count" tone="up-good" against={against} accent={charcoal}
            spark={dashboard.monthly.map((m) => m.invoices)} />
          <KeyCard label="Average invoice" figure={k.average_invoice} tone="up-good" against={against} accent={lighter}
            spark={dashboard.monthly.map(average)} />
          <KeyCard label={w.returns} figure={k.sales_returns} tone="up-neutral" against={against} accent={grey}
            spark={dashboard.monthly.map((m) => -toLakhs(m.returns))} />
        </div>
        <section className="card" aria-label={w.byMonth}>
          <div className="card-head">
            <h2 className="card-title">{w.byMonth} (₹ lakh)</h2>
            <span className="card-small-note">Click a month to open it</span>
          </div>
          <EChart
            key={props.dark ? 'dark' : 'light'}
            option={monthChart(dashboard.monthly, colours, w)}
            dark={props.dark}
            height={260}
            onClick={(i) => {
              const m = dashboard.monthly[i]
              if (m) window.location.hash = monthHref(m.month, query, w).slice(1)
            }}
          />
          <ExplorerTable id={`${w.module}-by-month`} label={w.byMonthTable} columns={monthColumns(query, w)} rows={dashboard.monthly} rowKey={(m) => m.month} totalLabel="Total" />
        </section>
        {props.side === 'sales' && dashboard.monthly_by_company.length > 0 && (
          <section className="card" aria-label="Monthly sales by branch">
            <div className="card-head">
              <h2 className="card-title">Monthly net sales by branch (₹ lakh)</h2>
              <span className="card-small-note">Hover for gross sales, returns and other adjustments</span>
            </div>
            <EChart
              key={props.dark ? 'dark' : 'light'}
              option={branchSalesChart(dashboard.monthly_by_company, companies, colours)}
              dark={props.dark}
              height={320}
            />
            <p className="report-note">Each series represents a selected company and uses its configured dashboard display name.</p>
          </section>
        )}
        {dashboard.channels.length > 0 && (
          <section className="card" aria-label={w.mix}>
            <h2 className="card-title">{w.mix}</h2>
            <Donut label={w.mixLabel} formula="F-SAL-009" dark={props.dark} colours={[colours.primary, colours.netProfit, colours.grossProfit, colours.neutralBar, colours.primaryLine]}
              parts={dashboard.channels.map((c) => ({ name: c.name, amount: c.net_sales, to: register(c.name) }))} />
          </section>
        )}
        <div className="sales-tables">
          <section className="card" aria-label={w.top}>
            <h2 className="card-title">{w.top}</h2>
            <ExplorerTable
              id={`${w.module}-top-parties`}
              label={w.top}
              columns={customerColumns(names, combined, query, net, w)}
              rows={dashboard.top_customers}
              rowKey={(p) => `${p.company}-${p.party_id}`}
              sortKey="net"
              descending
              note={`${dashboard.customers.toLocaleString('en-IN')} ${w.parties} had entries; the others and those without a party: ${formatExact(dashboard.other_customers)}.`}
            />
          </section>
          <section className="card" aria-label="Largest invoices">
            <h2 className="card-title">Largest invoices</h2>
            <ExplorerTable
              id={`${w.module}-largest-invoices`}
              label="Largest invoices"
              columns={invoiceColumns(names, combined, query, w)}
              rows={dashboard.largest_invoices}
              rowKey={(i) => String(i.voucher_id)}
              sortKey="amount"
              descending
              note={`An invoice's amount is its entries on the ${w.ledgers} (before taxes).`}
            />
          </section>
        </div>
      </>
    )
  }

  return (
    <div className="report-page">
      <div className="report-main">
        <div className="report-head">
          <div>
            {dashboard?.combined && <Typography.Text type="secondary">Several companies: {COMBINED_NOTE}</Typography.Text>}
          </div>
          <div className="report-toolbar"><WhatIsThis>props.side === 'sales' ? <Help sourceName={sourceName} /> : <PurchasesHelp sourceName={sourceName} /></WhatIsThis></div>
        </div>
        {content}
      </div>
    </div>
  )
}
