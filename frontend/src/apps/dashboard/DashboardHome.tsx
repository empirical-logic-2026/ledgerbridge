// The Overview (docs/design/dashboard.md Section 0.4, RPT-014), in the reference pattern: the
// key cards (net sales, gross profit with the gross margin, net profit with the net margin, cash
// and bank, customers), each with its change and a twelve-month sparkline; sales and purchases
// by month with each month's gross and net profit marked; sales by channel as a donut; the
// Profit & Loss summary against last year; the top customers with their status. Figures:
// core/home.py and core/overview.py (GET /api/v1/home); every formula: docs/formulas.md.
// Short amounts (₹4.82 Cr), the exact amount on hover; "—" with the reason where a figure
// needs a stored statement that isn't there. Everything opens the page behind it.

import { Money } from '../../components/Money.tsx'
import { Alert, Skeleton, Typography } from 'antd'
import type { Home, SummaryLine, TopCustomerOut } from '../../api/types.ts'
import { Donut } from '../../components/Donut.tsx'
import { EChart } from '../../components/EChart.tsx'
import { Explained } from '../../components/Explained.tsx'
import { KeyCard } from '../../components/KeyCard.tsx'
import { StatusPill } from '../../components/StatusPill.tsx'
import { formatChange, formatDate, toLakhs, toScaled } from '../../format.ts'
import { type Query } from '../../router.ts'
import { againstOf } from '../../selection.ts'
import { builtHref } from '../../shell/nav.ts'
import { tokens, type Tokens } from '../../theme.ts'
import { salesAndPurchases } from './homeChart.ts'
import { COMBINED_NOTE } from './words.ts'
import { partyPaymentStatusInfo } from '../../statuses.ts'

interface Props {
  home: Home | undefined
  loading: boolean
  error: Error | null
  dark: boolean
  query: Query // the selection, for the links
}

const OTHERS = 'Others'

/** An amount as the Amounts setting shows it (components/Money.tsx). */
const Amount = Money

function KeyFigures({ home, query, colours }: { home: Home; query: Query; colours: Tokens }) {
  const pl = home.profit_loss
  const against = againstOf(home.compared_with)
  const missing = pl.reason ? `Needs the stored statements: ${pl.reason}.` : undefined
  const profitLoss = builtHref(['pnl', 'profit-loss'], query)
  const trend = home.trend
  const lakhs = (values: (string | null)[]) => values.map((v) => (v === null ? null : toLakhs(v)))
  const margin = (value: string | null | undefined, label: string) => (value ? `${label} ${value}%` : undefined)
  const [green, charcoal, lighter, grey] = colours.accents
  return (
    <div className="home-kpis">
      <KeyCard label="Net sales" figure={pl.net_sales} against={against} missing={missing} accent={green}
        spark={lakhs(trend.map((t) => t.net_sales))} to={builtHref(['sales', 'dashboard'], query)} />
      <KeyCard label="Gross profit" figure={pl.gross_profit} against={against} missing={missing} accent={lighter}
        note={margin(pl.gross_margin_pct.value, 'Gross margin')} spark={lakhs(trend.map((t) => t.gross_profit))} to={profitLoss} />
      <KeyCard label="Net profit" figure={pl.net_profit} against={against} missing={missing} accent={charcoal}
        note={margin(pl.net_profit_pct.value, 'Net margin')} spark={lakhs(trend.map((t) => t.net_profit))} to={profitLoss} />
      <KeyCard label="Cash & bank" figure={{ value: home.balances.cash_and_bank }} accent={grey}
        note={`As at ${formatDate(home.balances.as_of)}`} spark={lakhs(trend.map((t) => t.cash_and_bank))} />
      <KeyCard
        label="Customers"
        figure={{ value: String(home.customers.value), before: home.customers.before == null ? null : String(home.customers.before), change_pct: home.customers.change_pct }}
        unit="count"
        against={against}
        accent={green}
        note="With sales in the period"
        spark={trend.map((t) => t.customers)}
        to={builtHref(['sales', 'customers'], query)}
      />
    </div>
  )
}

function Notes({ home }: { home: Home }) {
  const pl = home.profit_loss
  return (
    <>
      {pl.reason && <p className="card-note">Profit isn't available: {pl.reason}.</p>}
      {pl.cut && pl.as_of && <p className="card-note">Profit is to {formatDate(pl.as_of)}, the last statement stored in this period.</p>}
      {pl.shifted && (
        <p className="card-note">
          Months ending on the 30th (or in February) run to the 2nd of the next month: the source's statements exist
          only for the 1st, 2nd and 31st (Educational mode).
        </p>
      )}
      {home.compared_with && pl.before_reason && !pl.reason && <p className="card-note">No comparison for profit: {pl.before_reason}.</p>}
    </>
  )
}

/** "▲ 12%" or "▼ 1.1 pts", green when good for the business, crimson when bad, neutral for
 *  a cost going up. */
function Change({ line }: { line: SummaryLine }) {
  const change = line.unit === 'percent' ? line.change_pts : line.change_pct
  if (!change) return <span className="muted">—</span>
  const up = toScaled(change) >= 0n
  const tone = up === line.higher_is_better ? 'good' : line.higher_is_better ? 'bad' : 'neutral'
  const text = formatChange(change)
  return <span className={`change ${tone}`}>{line.unit === 'percent' ? text.replace(/%$/, ' pts') : text}</span>
}

function shown(line: SummaryLine, value: string | null | undefined) {
  if (value === null || value === undefined) return <span>—</span>
  return line.unit === 'percent' ? <span>{value}%</span> : <Amount value={value} />
}

function isTopCustomer(value: unknown): value is TopCustomerOut {
  if (typeof value !== 'object' || value === null) return false
  const customer = value as Record<string, unknown>
  return (
    typeof customer.party_id === 'number' &&
    typeof customer.name === 'string' &&
    typeof customer.net_sales === 'string' &&
    (typeof customer.share_pct === 'string' || customer.share_pct === null) &&
    typeof customer.balance === 'string'
  )
}

function Summary({ home, query }: { home: Home; query: Query }) {
  const to = builtHref(['pnl', 'profit-loss'], query)
  return (
    <section className="card" aria-label="Profit & Loss summary">
      <div className="card-head">
        <h2 className="card-title">Profit &amp; Loss summary</h2>
        {to && (
          <a href={to} className="card-open">
            Open →
          </a>
        )}
      </div>
      <div className="report-table-wrap">
      <table className="report-table compact" aria-label="Profit & Loss against last year">
        <thead>
          <tr>
            <th>Line</th>
            <th className="num"><Explained label="This period" /></th>
            <th className="num"><Explained label="Last year" /></th>
            <th className="num"><Explained label="Change" /></th>
          </tr>
        </thead>
        <tbody>
          {home.summary.map((line) => (
            <tr key={line.key} className={line.key.endsWith('profit') ? 'line-total' : undefined}>
              <th>{to ? <a href={to}><Explained label={line.label} /></a> : <Explained label={line.label} />}</th>
              <td className="num">{shown(line, line.value)}</td>
              <td className="num">{shown(line, line.last_year)}</td>
              <td className="num">
                <Change line={line} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>
      {home.summary_reason && <p className="card-note">No figures for last year: {home.summary_reason}.</p>}
    </section>
  )
}

function TopCustomers({ home, query }: { home: Home; query: Query }) {
  const list = builtHref(['sales', 'customers'], query)
  const hasCustomerList = Array.isArray(home.top_customers)
  const topCustomers = hasCustomerList ? home.top_customers.filter(isTopCustomer) : []
  const malformedCount = hasCustomerList ? home.top_customers.length - topCustomers.length : 0
  return (
    <section className="card" aria-label="Top customers">
      <div className="card-head">
        <h2 className="card-title">Top customers</h2>
        {list && (
          <a href={list} className="card-open">
            All customers →
          </a>
        )}
      </div>
      {!hasCustomerList ? (
        <Alert
          type="error"
          showIcon
          message="Customer data couldn't be displayed."
          description="The dashboard response did not include a valid customer list."
        />
      ) : (
        <>
          {malformedCount > 0 && (
            <Alert
              type="warning"
              showIcon
              message="Some customer rows couldn't be displayed."
              description={`${malformedCount} customer record${malformedCount === 1 ? '' : 's'} did not match the dashboard response format.`}
            />
          )}
          {topCustomers.length ? (
            <div className="report-table-wrap">
            <table className="report-table compact" aria-label="Top customers by net sales">
              <thead>
                <tr>
                  <th>Customer</th>
                  <th className="num"><Explained label="Net sales" /></th>
                  <th className="num"><Explained label="Share" /></th>
                  <th className="num"><Explained label="Balance due" /></th>
                  <th><Explained label="Status" /></th>
                  <th><Explained label="Meaning" /></th>
                </tr>
              </thead>
              <tbody>
                {topCustomers.map((c) => {
                  const to = builtHref(['sales', 'customers', String(c.party_id)], query)
                  const status = partyPaymentStatusInfo(c.payment_status ?? c.status, c.balance, 'customers')
                  return (
                    <tr key={c.party_id}>
                      <th className="wrap">{to ? <a href={to}>{c.name}</a> : c.name}</th>
                      <td className="num">
                        <Amount value={c.net_sales} />
                      </td>
                      <td className="num">{c.share_pct ? `${c.share_pct}%` : '—'}</td>
                      <td className="num">
                        <Amount value={c.balance} />
                      </td>
                      <td>
                        <StatusPill text={status.label} tone={status.tone} help={status.meaning} />
                      </td>
                      <td className="wrap">{status.meaning}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
            </div>
          ) : malformedCount > 0 ? null : (
            <Typography.Text type="secondary">No sales to customers in this period.</Typography.Text>
          )}
        </>
      )}
    </section>
  )
}

export function DashboardHome({ home, loading, error, dark, query }: Props) {
  if (error) return <Alert type="error" showIcon message="The figures couldn't be loaded." description={error.message} />
  if (loading || !home) return <Skeleton active paragraph={{ rows: 8 }} />
  const colours = tokens[dark ? 'dark' : 'light']
  const profitShown = home.monthly.some((m) => m.net_profit !== null)
  const register = (channel: string) => (channel === OTHERS ? undefined : builtHref(['sales', 'register'], { ...query, channel: [channel] }))
  return (
    <div className="home">
      {home.combined && (
        <div className="home-heading">
          <Typography.Text type="secondary">Several companies: {COMBINED_NOTE}</Typography.Text>
        </div>
      )}
      <KeyFigures home={home} query={query} colours={colours} />
      <Notes home={home} />
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
          {home.channels.length ? (
            <Donut label="Net sales by channel" dark={dark} colours={[colours.primary, colours.netProfit, colours.grossProfit, colours.neutralBar, colours.primaryLine]}
              parts={home.channels.map((c) => ({ name: c.name, amount: c.net_sales, to: register(c.name) }))} />
          ) : (
            <Typography.Text type="secondary">No sales in this period.</Typography.Text>
          )}
        </section>
      </div>
      <div className="home-tables">
        <Summary home={home} query={query} />
        <TopCustomers home={home} query={query} />
      </div>
    </div>
  )
}
