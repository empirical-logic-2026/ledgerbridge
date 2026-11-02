// Monthly sales and monthly purchases (docs/design/dashboard.md Section 0.2): each month's
// gross, returns, other adjustments, net and invoices, and the closing balance (the year to
// date, as the source's monthly summary of the group shows it); a chart of net by month and
// the closing balance; every month opens its register. Figures: core/sales.py
// (GET /api/v1/monthly/{side}).

import { Alert, Skeleton } from 'antd'
import type { EChartsOption } from 'echarts'
import type { Company, MonthOut, MonthlyOut } from '../../api/types.ts'
import { EChart } from '../../components/EChart.tsx'
import { formatExact, formatMonth, toLakhs } from '../../format.ts'
import type { ExplorerColumn } from '../../reporting/explorer.ts'
import { ExplorerTable } from '../../reporting/ExplorerTable.tsx'
import { ReportFrame, type PanelProps } from '../../reporting/ReportFrame.tsx'
import type { Query } from '../../router.ts'
import { builtHref } from '../../shell/nav.ts'
import { tokens, type Tokens } from '../../theme.ts'
import type { Side } from './Register.tsx'

interface Props extends PanelProps {
  side: Side
  companies: Company[]
  monthly: MonthlyOut | undefined
  loading: boolean
  error: Error | null
  dark: boolean
}

const WORDS: Record<Side, { title: string; net: string; group: string; returns: string; register: string[]; tally: string }> = {
  sales: { title: 'Monthly sales', net: 'Net sales', group: 'Sales Accounts', returns: 'credit notes', register: ['sales', 'register'], tally: 'Sales Register' },
  purchases: {
    title: 'Monthly purchases',
    net: 'Net purchases',
    group: 'Purchase Accounts',
    returns: 'debit notes',
    register: ['purchases', 'register'],
    tally: 'Purchase Register',
  },
}

/** A month opens its register for that month. */
function monthHref(side: Side, month: string, query: Query): string | undefined {
  return builtHref(WORDS[side].register, { ...query, month: month.slice(0, 7), from: undefined, to: undefined })
}

function columns(side: Side, query: Query): ExplorerColumn<MonthOut>[] {
  const link = (m: MonthOut) => monthHref(side, m.month, query)
  return [
    { key: 'month', label: 'Month', kind: 'text', value: (m) => formatMonth(m.month), link },
    { key: 'gross', label: 'Gross', kind: 'amount', value: (m) => m.gross },
    { key: 'returns', label: 'Returns', kind: 'amount', value: (m) => m.returns },
    { key: 'other', label: 'Other adjustments', kind: 'amount', value: (m) => m.other },
    { key: 'net', label: WORDS[side].net, kind: 'amount', value: (m) => m.net, link },
    { key: 'closing', label: 'Closing balance', kind: 'amount', value: (m) => m.closing, summed: false },
    { key: 'invoices', label: 'Invoices', kind: 'count', value: (m) => m.invoices },
  ]
}

function chart(side: Side, months: MonthOut[], colours: Tokens): EChartsOption {
  const text = colours.muted
  return {
    backgroundColor: 'transparent',
    grid: { left: 52, right: 52, top: 24, bottom: 28 },
    legend: { top: 0, right: 0, textStyle: { color: text }, data: [WORDS[side].net, 'Closing balance'] },
    tooltip: {
      trigger: 'axis',
      formatter: (params: unknown) => {
        const [first] = params as { dataIndex: number }[]
        const m = months[first.dataIndex]
        return `${formatMonth(m.month)}<br/>${WORDS[side].net} ${formatExact(m.net)}<br/>Closing balance ${formatExact(m.closing)}`
      },
    },
    xAxis: { type: 'category', data: months.map((m) => formatMonth(m.month).slice(0, 3)), axisLabel: { color: text } },
    yAxis: [
      { type: 'value', axisLabel: { color: text }, splitLine: { lineStyle: { color: colours.border } } },
      { type: 'value', axisLabel: { color: text }, splitLine: { show: false } },
    ],
    series: [
      { type: 'bar', name: WORDS[side].net, data: months.map((m) => toLakhs(m.net)), itemStyle: { color: side === 'sales' ? colours.primary : colours.neutralBar } },
      { type: 'line', name: 'Closing balance', yAxisIndex: 1, data: months.map((m) => toLakhs(m.closing)), itemStyle: { color: colours.text }, lineStyle: { color: colours.text } },
    ],
  }
}

function help(side: Side) {
  const w = WORDS[side]
  return function Help(sourceName: string) {
    return (
      <>
        <p>
          Each month's entries on the ledgers under {sourceName}'s {w.group} group: <strong>gross</strong> on invoices, <strong>returns</strong> on{' '}
          {w.returns} (negative), <strong>other adjustments</strong> on any other voucher (journals and the like), and the <strong>net</strong>, their
          sum. The <strong>closing balance</strong> is the net from the start of the financial year to the month's end.
        </p>
        <p>
          <strong>Where the figures come from:</strong> the books, rebuilt after every sync. {side === 'sales' ? "Monthly sales are proven day by day against the source's own statements (./dev.ps1 validate monthly-sales)." : 'The same definition as monthly sales, on the purchase side.'}
        </p>
        <p>
          <strong>To compare with {sourceName}:</strong> open the {w.group} group's monthly summary for the same year (from the Profit &amp; Loss,
          drill into the group): the debits, credits and closing balance by month. The {w.tally} lists each month's vouchers.
        </p>
      </>
    )
  }
}

export function Monthly(props: Props) {
  const { side, monthly } = props
  const colours = tokens[props.dark ? 'dark' : 'light']
  let content: React.ReactNode
  if (props.error) {
    content = <Alert type="error" showIcon message="The months couldn't be loaded." description={props.error.message} />
  } else if (props.loading || !monthly) {
    content = <Skeleton active paragraph={{ rows: 10 }} />
  } else {
    content = (
      <section className="card" aria-label={`${WORDS[side].net} by month`}>
        <EChart
          key={props.dark ? 'dark' : 'light'}
          option={chart(side, monthly.months, colours)}
          dark={props.dark}
          height={260}
          onClick={(i) => {
            const to = monthly.months[i] && monthHref(side, monthly.months[i].month, props.query)
            if (to) window.location.hash = to.slice(1)
          }}
        />
        <ExplorerTable id={`${side}-monthly`} label={WORDS[side].title} columns={columns(side, props.query)} rows={monthly.months} rowKey={(m) => m.month} totalLabel="Total" />
      </section>
    )
  }
  return (
    <ReportFrame {...props} title={WORDS[side].title} page={`${side}-monthly`} period={monthly?.period} combined={monthly?.combined ?? false} help={help(side)}>
      {content}
    </ReportFrame>
  )
}
