// The Sales dashboard (docs/design/dashboard.md Section 0.2, screen 7): key figures with the
// change against the comparison period (net sales, invoices, average invoice, sales returns), net sales by
// month (a month opens its register once that page is built; a table below gives every
// month's gross, returns, other adjustments and net), the top customers and the largest
// invoices, each table in the table explorer; the options side panel with "What is this?".
// Figures: core/sales.py (GET /api/v1/sales/dashboard).

import { Alert, Button, Skeleton, Typography } from 'antd'
import type { EChartsOption } from 'echarts'
import type { Company, InvoiceOut, MonthSales, PartySales, SalesDashboard as Dashboard } from '../../api/types.ts'
import { EChart } from '../../components/EChart.tsx'
import { KeyCard } from '../../components/KeyCard.tsx'
import { againstOf } from '../../selection.ts'
import { formatDate, formatExact, formatMonth, toLakhs, toScaled } from '../../format.ts'
import type { ExplorerColumn } from '../../reporting/explorer.ts'
import { ExplorerTable } from '../../reporting/ExplorerTable.tsx'
import { OptionsPanel, type Related } from '../../reporting/OptionsPanel.tsx'
import type { Query } from '../../router.ts'
import { builtHref } from '../../shell/nav.ts'
import { tokens, type Tokens } from '../../theme.ts'
import { COMBINED_NOTE } from '../dashboard/DashboardHome.tsx'

interface Props {
  companies: Company[] // the selected ones
  dashboard: Dashboard | undefined
  loading: boolean
  error: Error | null
  dark: boolean
  query: Query // the selection, kept on every link
  panelOpen: boolean
  onPanel: (open: boolean) => void
  currentQuery: string
  onApplyView: (query: string) => void
  related: Related[]
}

function monthChart(months: MonthSales[], colours: Tokens): EChartsOption {
  const text = colours.muted
  return {
    backgroundColor: 'transparent',
    grid: { left: 48, right: 12, top: 16, bottom: 28 },
    tooltip: {
      trigger: 'axis',
      formatter: (params: unknown) => {
        const [first] = params as { dataIndex: number }[]
        const m = months[first.dataIndex]
        return `${formatMonth(m.month)}<br/>Net sales ${formatExact(m.net)}<br/>Invoices ${m.invoices}`
      },
    },
    xAxis: { type: 'category', data: months.map((m) => formatMonth(m.month).slice(0, 3)), axisLabel: { color: text } },
    yAxis: { type: 'value', axisLabel: { color: text }, splitLine: { lineStyle: { color: colours.border } } },
    series: [
      {
        type: 'line',
        name: 'Net sales',
        data: months.map((m) => toLakhs(m.net)),
        itemStyle: { color: colours.primary },
        lineStyle: { color: colours.primary, width: 2 },
        symbolSize: 8,
        areaStyle: { color: colours.primarySoft, opacity: 0.6 },
      },
    ],
  }
}

/** The page a month opens: its sales register once built, else this page for that month. */
function monthHref(month: string, query: Query): string {
  const one = { ...query, month: month.slice(0, 7), from: undefined, to: undefined }
  return builtHref(['sales', 'register'], one) ?? builtHref(['sales', 'dashboard'], one) ?? '#'
}

/** A customer opens their page once built, else this page filtered to them. */
function customerHref(p: { party_id: number | null; name: string | null }, query: Query): string | undefined {
  if (p.party_id === null || !p.name) return undefined
  return builtHref(['sales', 'customers', String(p.party_id)], query) ?? builtHref(['sales', 'dashboard'], { ...query, customer: [p.name] })
}

function monthColumns(query: Query): ExplorerColumn<MonthSales>[] {
  return [
    { key: 'month', label: 'Month', kind: 'text', value: (m) => formatMonth(m.month), link: (m) => monthHref(m.month, query) },
    { key: 'gross', label: 'Gross', kind: 'amount', value: (m) => m.gross },
    { key: 'returns', label: 'Returns', kind: 'amount', value: (m) => m.returns },
    { key: 'other', label: 'Other adjustments', kind: 'amount', value: (m) => m.other },
    { key: 'net', label: 'Net sales', kind: 'amount', value: (m) => m.net, link: (m) => monthHref(m.month, query) },
    { key: 'invoices', label: 'Invoices', kind: 'count', value: (m) => m.invoices },
  ]
}

function customerColumns(names: Map<number, string>, combined: boolean, query: Query, total: string): ExplorerColumn<PartySales>[] {
  const share = (net: string) => {
    const all = toScaled(total)
    return all > 0n ? `${(Number((toScaled(net) * 1000n) / all) / 10).toFixed(1)}%` : null
  }
  return [
    { key: 'name', label: 'Customer', kind: 'text', value: (p) => p.name, link: (p) => customerHref({ party_id: p.party_id, name: p.name }, query) },
    { key: 'company', label: 'Company', kind: 'text', value: (p) => names.get(p.company) ?? `Company ${p.company}`, groupable: true, hidden: !combined },
    { key: 'net', label: 'Net sales', kind: 'amount', value: (p) => p.net_sales },
    { key: 'share', label: 'Share', kind: 'text', value: (p) => share(p.net_sales) },
    { key: 'invoices', label: 'Invoices', kind: 'count', value: (p) => p.invoices },
  ]
}

function invoiceColumns(names: Map<number, string>, combined: boolean, query: Query): ExplorerColumn<InvoiceOut>[] {
  return [
    { key: 'date', label: 'Date', kind: 'date', value: (i) => i.date },
    { key: 'number', label: 'Vch No.', kind: 'text', value: (i) => i.number, link: (i) => builtHref(['books', 'vouchers', String(i.voucher_id)], query) },
    { key: 'type', label: 'Vch Type', kind: 'text', value: (i) => i.voucher_type, groupable: true },
    { key: 'party', label: 'Customer', kind: 'text', value: (i) => i.party, link: (i) => customerHref({ party_id: i.party_id, name: i.party }, query), groupable: true },
    { key: 'company', label: 'Company', kind: 'text', value: (i) => names.get(i.company) ?? `Company ${i.company}`, groupable: true, hidden: !combined },
    { key: 'amount', label: 'Amount', kind: 'amount', value: (i) => i.amount },
  ]
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
  const sourceName = companies[0]?.health.source_name ?? 'the source'
  const names = new Map(companies.map((c) => [c.id, c.name]))
  const title = companies.map((c) => c.name).join(' + ')
  const colours = tokens[props.dark ? 'dark' : 'light']

  let content: React.ReactNode
  if (props.error) {
    content = <Alert type="error" showIcon message="The sales couldn't be loaded." description={props.error.message} />
  } else if (props.loading || !dashboard) {
    content = <Skeleton active paragraph={{ rows: 10 }} />
  } else {
    const k = dashboard.key_figures
    const combined = dashboard.combined
    const net = k.net_sales.value ?? '0'
    content = (
      <>
        <div className="sales-cards">
          <KeyCard label="Net sales" figure={k.net_sales} tone="up-good" against={againstOf(dashboard.compared_with)} />
          <KeyCard label="Invoices" figure={k.invoices} unit="count" tone="up-good" against={againstOf(dashboard.compared_with)} />
          <KeyCard label="Average invoice" figure={k.average_invoice} tone="up-good" against={againstOf(dashboard.compared_with)} />
          <KeyCard label="Sales returns" figure={k.sales_returns} tone="up-neutral" against={againstOf(dashboard.compared_with)} />
        </div>
        <section className="card" aria-label="Net sales by month">
          <div className="card-head">
            <h2 className="card-title">Net sales by month (₹ lakh)</h2>
            <span className="card-small-note">Click a month to open it</span>
          </div>
          <EChart
            key={props.dark ? 'dark' : 'light'}
            option={monthChart(dashboard.monthly, colours)}
            dark={props.dark}
            height={260}
            onClick={(i) => {
              const m = dashboard.monthly[i]
              if (m) window.location.hash = monthHref(m.month, query).slice(1)
            }}
          />
          <ExplorerTable id="sales-by-month" label="Sales by month" columns={monthColumns(query)} rows={dashboard.monthly} rowKey={(m) => m.month} totalLabel="Total" />
        </section>
        <div className="sales-tables">
          <section className="card" aria-label="Top customers">
            <h2 className="card-title">Top customers</h2>
            <ExplorerTable
              id="sales-top-customers"
              label="Top customers"
              columns={customerColumns(names, combined, query, net)}
              rows={dashboard.top_customers}
              rowKey={(p) => `${p.company}-${p.party_id}`}
              sortKey="net"
              descending
              note={`${dashboard.customers.toLocaleString('en-IN')} customers had sales; the others and sales without a party: ${formatExact(dashboard.other_customers)}.`}
            />
          </section>
          <section className="card" aria-label="Largest invoices">
            <h2 className="card-title">Largest invoices</h2>
            <ExplorerTable
              id="sales-largest-invoices"
              label="Largest invoices"
              columns={invoiceColumns(names, combined, query)}
              rows={dashboard.largest_invoices}
              rowKey={(i) => String(i.voucher_id)}
              sortKey="amount"
              descending
              note="An invoice's amount is its entries on the sales ledgers (before taxes)."
            />
          </section>
        </div>
      </>
    )
  }

  return (
    <div className={props.panelOpen ? 'report-page with-panel' : 'report-page'}>
      <div className="report-main">
        <div className="report-head">
          <div>
            <Typography.Title level={2} className="report-title">
              Sales · {title}
            </Typography.Title>
            {dashboard && (
              <Typography.Text type="secondary">
                {formatDate(dashboard.period.start)} to {formatDate(dashboard.period.end)}
                {dashboard.combined ? ` · ${COMBINED_NOTE}` : ''}
              </Typography.Text>
            )}
          </div>
          <div className="report-toolbar">{!props.panelOpen && <Button onClick={() => props.onPanel(true)}>Options</Button>}</div>
        </div>
        {content}
      </div>
      {props.panelOpen && (
        <OptionsPanel
          title="Sales options"
          page="sales-dashboard"
          matching={undefined}
          companiesLabel={companies.length === 1 ? companies[0].name : `all ${companies.length} companies`}
          sourceName={sourceName}
          related={props.related}
          query={query}
          currentQuery={props.currentQuery}
          onApplyView={props.onApplyView}
          help={<Help sourceName={sourceName} />}
          onClose={() => props.onPanel(false)}
        />
      )}
    </div>
  )
}
