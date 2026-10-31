// The Reports app's Dashboard (docs/design/dashboard.md Section 0.1, screen 5): the Profit &
// Loss and Balance Sheet cards, cash and bank, receivables, payables and stock value, and
// three charts: sales and purchases by month, sales by channel (voucher type), and each
// company's share of sales. Figures: core/home.py (GET /api/v1/home). Short amounts on the
// cards (₹4.82 Cr), the exact amount on hover; "—" with the reason where a figure needs a
// stored statement that isn't there.

import { Alert, Skeleton, Tooltip, Typography } from 'antd'
import type { EChartsOption } from 'echarts'
import type { Company, Figure, Home } from '../../api/types.ts'
import { EChart } from '../../components/EChart.tsx'
import { formatChange, formatCompact, formatDate, formatExact, formatMonth, toLakhs, toScaled } from '../../format.ts'
import { href, type Query } from '../../router.ts'
import { tokens, type Tokens } from '../../theme.ts'

export const COMBINED_NOTE = 'combined, without inter-company eliminations'

interface Props {
  companies: Company[] // the selected ones
  home: Home | undefined
  loading: boolean
  error: Error | null
  dark: boolean
  query: Query // the selection, for the cards' Open links
}

function Amount({ value, missing }: { value: string | null | undefined; missing?: string | null }) {
  if (value === null || value === undefined) {
    return (
      <Tooltip title={missing ?? undefined}>
        <span>—</span>
      </Tooltip>
    )
  }
  return (
    <Tooltip title={formatExact(value)}>
      <span className={toScaled(value) < 0n ? 'negative' : undefined}>{formatCompact(value)}</span>
    </Tooltip>
  )
}

/** ▲ 12% in green when the change is good for the business; red when it is bad for it
 *  (sales or profit down); neutral for costs going up, so that red keeps its meaning. */
function Change({ figure, higherIsBetter }: { figure: Figure; higherIsBetter: boolean }) {
  if (!figure.change_pct) return null
  const up = toScaled(figure.change_pct) >= 0n
  const good = up === higherIsBetter
  return (
    <Tooltip title={figure.last_year ? `Last year ${formatExact(figure.last_year)}` : undefined}>
      <span className={good ? 'change good' : higherIsBetter ? 'change bad' : 'change neutral'}>{formatChange(figure.change_pct)}</span>
    </Tooltip>
  )
}

function Row({ label, value, missing, change }: { label: string; value: string | null | undefined; missing?: string | null; change?: React.ReactNode }) {
  return (
    <div className="card-row">
      <span>{label}</span>
      <span className="card-row-value">
        <Amount value={value} missing={missing} />
        {change}
      </span>
    </div>
  )
}

function ProfitLossCard({ home, query }: { home: Home; query: Query }) {
  const pl = home.profit_loss
  const lines: [string, Figure, boolean][] = [
    ['Net sales', pl.net_sales, true],
    ['Cost of sales', pl.cost_of_sales, false],
    ['Gross profit', pl.gross_profit, true],
    ['Net profit', pl.net_profit, true],
  ]
  return (
    <section className="card card-wide" aria-label="Profit & Loss">
      <div className="card-head">
        <h2 className="card-title">Profit &amp; Loss</h2>
        <a href={href(['reports', 'profit-loss'], query)} className="card-open">
          Open →
        </a>
      </div>
      {lines.map(([label, figure, higher]) => (
        <Row key={label} label={label} value={figure.value} missing={pl.reason} change={<Change figure={figure} higherIsBetter={higher} />} />
      ))}
      {pl.reason && <p className="card-note">Profit isn't available: {pl.reason}.</p>}
      {pl.shifted && (
        <p className="card-note">
          Months ending on the 30th (or in February) run to the 2nd of the next month: the source's statements exist
          only for the 1st, 2nd and 31st (Educational mode).
        </p>
      )}
      {pl.last_year_reason && !pl.reason && <p className="card-note">No comparison: {pl.last_year_reason}.</p>}
    </section>
  )
}

function BalanceSheetCard({ home }: { home: Home }) {
  const bs = home.balance_sheet
  const lines: [string, string | null | undefined][] = [
    ['Total assets', bs.total_assets],
    ['Current assets', bs.current_assets],
    ['Current liabilities', bs.current_liabilities],
    ['Capital and reserves (incl. profit to date)', bs.capital_and_reserves],
  ]
  return (
    <section className="card card-wide" aria-label="Balance Sheet">
      <h2 className="card-title">Balance Sheet</h2>
      {lines.map(([label, value]) => (
        <Row key={label} label={label} value={value} missing={bs.reason} />
      ))}
      <p className="card-note">{bs.as_of ? `As at ${formatDate(bs.as_of)}` : `Not available: ${bs.reason}.`}</p>
    </section>
  )
}

function SmallCard({ label, value, note, missing }: { label: string; value: string | null | undefined; note: string; missing?: string }) {
  return (
    <section className="card card-small" aria-label={label}>
      <span className="card-small-label">{label}</span>
      <span className="card-small-value">
        <Amount value={value} missing={missing} />
      </span>
      <span className="card-small-note">{note}</span>
    </section>
  )
}

function salesAndPurchases(home: Home, colours: Tokens): EChartsOption {
  const months = home.monthly
  const text = colours.muted
  return {
    backgroundColor: 'transparent',
    grid: { left: 48, right: 8, top: 16, bottom: 28 },
    tooltip: {
      trigger: 'axis',
      formatter: (params: unknown) => {
        const [first] = params as { dataIndex: number }[]
        const m = months[first.dataIndex]
        return `${formatMonth(m.month)}<br/>Sales ${formatExact(m.sales)}<br/>Purchases ${formatExact(m.purchases)}`
      },
    },
    xAxis: { type: 'category', data: months.map((m) => formatMonth(m.month).slice(0, 3)), axisLabel: { color: text } },
    yAxis: { type: 'value', axisLabel: { color: text }, splitLine: { lineStyle: { color: colours.border } } },
    series: [
      { type: 'bar', name: 'Sales', data: months.map((m) => toLakhs(m.sales)), itemStyle: { color: colours.primary } },
      { type: 'bar', name: 'Purchases', data: months.map((m) => toLakhs(m.purchases)), itemStyle: { color: colours.neutralBar } },
    ],
  }
}

/** Horizontal bars as plain markup (screen 5): a label, the amount and a bar per row. */
function Bars({ rows, colour, value }: { rows: { label: string; amount: string; share: number }[]; colour: string; value: (row: { amount: string; share: number }) => string }) {
  return (
    <div className="bars">
      {rows.map((r) => (
        <div key={r.label} className="bar-row">
          <div className="bar-head">
            <span>{r.label}</span>
            <Tooltip title={formatExact(r.amount)}>
              <span className="bar-value">{value(r)}</span>
            </Tooltip>
          </div>
          <div className="bar-track">
            <div className="bar-fill" style={{ width: `${Math.max(0, Math.min(100, r.share))}%`, background: colour }} />
          </div>
        </div>
      ))}
    </div>
  )
}

function shareOf(amount: string, largest: string): number {
  const top = toScaled(largest)
  if (top <= 0n) return 0
  return Number((toScaled(amount) * 1000n) / top) / 10
}

export function DashboardHome({ companies, home, loading, error, dark, query }: Props) {
  if (error) return <Alert type="error" showIcon message="The figures couldn't be loaded." description={error.message} />
  if (loading || !home) return <Skeleton active paragraph={{ rows: 8 }} />
  const colours = tokens[dark ? 'dark' : 'light']
  const names = new Map(companies.map((c) => [c.id, c.name]))
  const source = companies[0]?.health.source_name ?? 'the source'
  const asAt = `As at ${formatDate(home.balances.as_of)}`
  const channels = home.channels
  const largestChannel = channels.reduce((max, c) => (toScaled(c.net_sales) > toScaled(max) ? c.net_sales : max), '0')
  return (
    <div className="home">
      <div className="home-heading">
        <Typography.Text type="secondary">
          {formatDate(home.period.start)} to {formatDate(home.period.end)}
          {home.combined ? ` · ${COMBINED_NOTE}` : ''}
        </Typography.Text>
      </div>
      <div className="home-cards">
        <ProfitLossCard home={home} query={query} />
        <BalanceSheetCard home={home} />
        <div className="home-small">
          <SmallCard label="Cash & bank" value={home.balances.cash_and_bank} note={asAt} />
          <SmallCard label="Receivables" value={home.balances.receivables} note={asAt} />
          <SmallCard label="Payables" value={home.balances.payables} note={asAt} />
          <SmallCard
            label="Stock value"
            value={home.balances.stock_value}
            note={home.balances.stock_value_as_of ? `from ${source}, ${formatDate(home.balances.stock_value_as_of)}` : `from ${source}`}
            missing="Stored with the statements; none for this date."
          />
        </div>
      </div>
      <div className="home-charts">
        <section className="card" aria-label="Sales and purchases by month">
          <div className="card-head">
            <h2 className="card-title">Sales and purchases by month (₹ lakh)</h2>
            <span className="legend">
              <span className="legend-key" style={{ background: colours.primary }} /> Sales <span className="legend-key" style={{ background: colours.neutralBar }} /> Purchases
            </span>
          </div>
          <EChart key={dark ? 'dark' : 'light'} option={salesAndPurchases(home, colours)} dark={dark} height={300} />
        </section>
        <section className="card" aria-label="Sales by channel">
          <h2 className="card-title">Sales by channel</h2>
          {channels.length ? (
            <Bars
              rows={channels.map((c) => ({ label: c.name, amount: c.net_sales, share: shareOf(c.net_sales, largestChannel) }))}
              colour={colours.primaryLine}
              value={(r) => formatCompact(r.amount)}
            />
          ) : (
            <Typography.Text type="secondary">No sales in this period.</Typography.Text>
          )}
        </section>
        <section className="card" aria-label="Share of sales by company">
          <h2 className="card-title">Share of sales by company</h2>
          <Bars
            rows={home.by_company.map((c) => ({
              label: names.get(c.company) ?? `Company ${c.company}`,
              amount: c.net_sales,
              share: c.share_pct ? Number(c.share_pct) : 0,
            }))}
            colour={colours.primary}
            value={(r) => (r.share ? `${Math.round(r.share)}%` : '—')}
          />
        </section>
      </div>
    </div>
  )
}
