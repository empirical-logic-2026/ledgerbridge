// The Reports app's Dashboard (docs/design/dashboard.md Section 0.1, screen 5): the key
// figures (revenue, gross margin, net profit, net profit %, customers), cash and bank,
// receivables, payables and stock value, and three charts: sales and purchases by month with
// each month's gross and net profit marked, sales by channel (voucher type), and each
// company's share of sales. Figures: core/home.py (GET /api/v1/home); every formula:
// docs/formulas.md. Short amounts on the cards (₹4.82 Cr), the exact amount on hover; "—"
// with the reason where a figure needs a stored statement that isn't there.

import { Alert, Skeleton, Tooltip, Typography } from 'antd'
import type { Company, Home, Ratio } from '../../api/types.ts'
import { EChart } from '../../components/EChart.tsx'
import { KeyCard } from '../../components/KeyCard.tsx'
import { againstOf } from '../../selection.ts'
import { formatCompact, formatDate, formatExact, toScaled } from '../../format.ts'
import { type Query } from '../../router.ts'
import { builtHref } from '../../shell/nav.ts'
import { tokens } from '../../theme.ts'
import { salesAndPurchases } from './homeChart.ts'

export const COMBINED_NOTE = 'combined, without inter-company eliminations'

interface Props {
  companies: Company[] // the selected ones
  home: Home | undefined
  loading: boolean
  error: Error | null
  dark: boolean
  query: Query // the selection, for the cards' links
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

function KeyFigures({ home, query }: { home: Home; query: Query }) {
  const pl = home.profit_loss
  const against = againstOf(home.compared_with)
  const missing = pl.reason ? `Needs the stored statements: ${pl.reason}.` : undefined
  const profitLoss = builtHref(['pnl', 'profit-loss'], query)
  const percent = (ratio: Ratio) => ({ value: ratio.value, before: ratio.before, change_pct: ratio.change_pts })
  const ofRevenue = pl.gross_margin_pct.value ? `${pl.gross_margin_pct.value}% of revenue` : undefined
  const customers = home.customers
  return (
    <>
      <div className="home-kpis">
        <KeyCard label="Revenue" figure={pl.net_sales} against={against} missing={missing} note="Net sales" to={builtHref(['sales', 'dashboard'], query)} />
        <KeyCard label="Gross margin" figure={pl.gross_profit} against={against} missing={missing} note={ofRevenue} to={profitLoss} />
        <KeyCard label="Net profit" figure={pl.net_profit} against={against} missing={missing} to={profitLoss} />
        <KeyCard label="Net profit %" figure={percent(pl.net_profit_pct)} unit="percent" against={against} missing={missing} note="Of revenue" to={profitLoss} />
        <KeyCard
          label="Customers"
          figure={{ value: String(customers.value), before: customers.before == null ? null : String(customers.before), change_pct: customers.change_pct }}
          unit="count"
          against={against}
          note="With sales in the period"
          to={builtHref(['sales', 'customers'], query)}
        />
      </div>
      {pl.reason && <p className="card-note">Profit isn't available: {pl.reason}.</p>}
      {pl.shifted && (
        <p className="card-note">
          Months ending on the 30th (or in February) run to the 2nd of the next month: the source's statements exist
          only for the 1st, 2nd and 31st (Educational mode).
        </p>
      )}
      {pl.cut && pl.as_of && <p className="card-note">Profit is to {formatDate(pl.as_of)}, the last statement stored in this period.</p>}
      {against && pl.before_reason && !pl.reason && <p className="card-note">No comparison for profit: {pl.before_reason}.</p>}
    </>
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
  const profitShown = home.monthly.some((m) => m.net_profit !== null)
  const largestChannel = channels.reduce((max, c) => (toScaled(c.net_sales) > toScaled(max) ? c.net_sales : max), '0')
  return (
    <div className="home">
      <div className="home-heading">
        <Typography.Text type="secondary">
          {formatDate(home.period.start)} to {formatDate(home.period.end)}
          {home.combined ? ` · ${COMBINED_NOTE}` : ''}
        </Typography.Text>
      </div>
      <KeyFigures home={home} query={query} />
      <div className="home-cards">
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
              <span className="legend-line" style={{ borderColor: colours.grossProfit }} /> Gross profit
              <span className="legend-line dashed" style={{ borderColor: colours.netProfit }} /> Net profit
            </span>
          </div>
          <EChart key={dark ? 'dark' : 'light'} option={salesAndPurchases(home, colours)} dark={dark} height={300} />
          {!profitShown && <p className="card-note">No profit marked: each month's profit needs its stored statements.</p>}
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
