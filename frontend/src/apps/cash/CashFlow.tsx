// The Cash Flow module, a simple cash movement (docs/design/dashboard.md Section 0.4): key cards
// (cash and bank at the start, money in, money out, cash and bank at the end), a waterfall from
// the opening through each category to the closing, the months' in and out, and the categories
// in the table explorer. The full statement (operating, investing, financing) is planned
// separately: it needs every ledger classified. Figures: core/cash_flow.py (GET
// /api/v1/cash-flow); formulas F-CF-001, F-CF-002.

import { Typography } from 'antd'
import { ErrorState } from '../../components/loading/ErrorState.tsx'
import { Loading } from '../../components/loading/Loading.tsx'
import type { EChartsOption } from 'echarts'
import type { CashFlowOut, Company, MovementOut } from '../../api/types.ts'
import { EChart } from '../../components/EChart.tsx'
import { KeyCard } from '../../components/KeyCard.tsx'
import { Waterfall } from '../../components/Waterfall.tsx'
import { formatDate, formatExact, formatMonth, toLakhs, toScaled } from '../../format.ts'
import { fromScaled, type ExplorerColumn } from '../../reporting/explorer.ts'
import { ExplorerTable } from '../../reporting/ExplorerTable.tsx'
import { ReportFrame, type PanelProps } from '../../reporting/ReportFrame.tsx'
import { tokens, type Tokens } from '../../theme.ts'

interface Props extends PanelProps {
  companies: Company[]
  flow: CashFlowOut | undefined
  loading: boolean
  error: Error | null
  onRetry?: () => void // ask again after an error
  dark: boolean
}

const COLUMNS: ExplorerColumn<MovementOut>[] = [
  { key: 'label', label: 'For', kind: 'text', value: (m) => m.label },
  { key: 'inflow', label: 'Money in', kind: 'amount', value: (m) => m.inflow },
  { key: 'outflow', label: 'Money out', kind: 'amount', value: (m) => m.outflow },
  { key: 'net', label: 'Net', kind: 'amount', value: (m) => m.net },
]

function monthly(flow: CashFlowOut, colours: Tokens): EChartsOption {
  return {
    backgroundColor: 'transparent',
    grid: { left: 48, right: 8, top: 16, bottom: 28 },
    tooltip: {
      trigger: 'axis',
      formatter: (params: unknown) => {
        const m = flow.monthly[(params as { dataIndex: number }[])[0].dataIndex]
        return `${formatMonth(m.month)}<br/>In ${formatExact(m.inflow)}<br/>Out ${formatExact(m.outflow)}`
      },
    },
    xAxis: { type: 'category', data: flow.monthly.map((m) => formatMonth(m.month).slice(0, 3)), axisLabel: { color: colours.muted } },
    yAxis: { type: 'value', axisLabel: { color: colours.muted }, splitLine: { lineStyle: { color: colours.border } } },
    series: [
      { type: 'bar', name: 'In', data: flow.monthly.map((m) => toLakhs(m.inflow)), itemStyle: { color: colours.primary } },
      { type: 'bar', name: 'Out', data: flow.monthly.map((m) => toLakhs(m.outflow)), itemStyle: { color: colours.neutralBar } },
    ],
  }
}

function help(sourceName: string) {
  return (
    <>
      <p>
        The money into and out of cash and bank in the period, by what it was for: each voucher's cash amount goes to the group of its other ledgers
        (customers, suppliers, income, expenses, taxes, loans, capital, fixed assets and investments), split by their amounts when there are
        several. Transfers between cash and bank net to nothing. The opening plus every movement is the closing (formula F-CF-001).
      </p>
      <p>
        This is a cash movement, not yet the full cash flow statement (operating, investing and financing activities): that needs every ledger
        classified, and is planned separately.
      </p>
      <p>
        <strong>To compare with {sourceName}:</strong> Display More Reports → Account Books → Cash/Bank Book(s) for the same period.
      </p>
    </>
  )
}

export function CashFlow(props: Props) {
  const { flow } = props
  const colours = tokens[props.dark ? 'dark' : 'light']
  let content: React.ReactNode
  if (props.error) {
    content = <ErrorState message="The cash movement couldn't be loaded." error={props.error} onRetry={props.onRetry} />
  } else if (props.loading || !flow) {
    content = <Loading shape="dashboard" />
  } else {
    const total = (key: 'inflow' | 'outflow') => fromScaled(flow.movements.reduce((sum, m) => sum + toScaled(m[key]), 0n))
    const [green, charcoal, lighter, grey] = colours.accents
    const steps = [
      { label: 'Opening', amount: flow.opening },
      ...flow.movements.filter((m) => toScaled(m.net) !== 0n).map((m) => ({ label: m.label, amount: m.net })),
      { label: 'Closing', amount: flow.closing },
    ]
    content = (
      <>
        <div className="sales-cards">
          <KeyCard label="Cash & bank at the start" figure={{ value: flow.opening }} note={`On ${formatDate(flow.start)}, before the period`} accent={grey} />
          <KeyCard label="Money in" figure={{ value: total('inflow') }} accent={green} spark={flow.monthly.map((m) => toLakhs(m.inflow))} />
          <KeyCard label="Money out" figure={{ value: total('outflow') }} accent={charcoal} spark={flow.monthly.map((m) => toLakhs(m.outflow))} />
          <KeyCard label="Cash & bank at the end" figure={{ value: flow.closing }} note={`As at ${formatDate(flow.end)}`} accent={lighter} />
        </div>
        <div className="home-charts">
          <section className="card" aria-label="From the opening to the closing">
            <h2 className="card-title">From the opening to the closing (₹ lakh)</h2>
            <Waterfall steps={steps} colours={colours} dark={props.dark} />
          </section>
          <section className="card" aria-label="Money in and out by month">
            <h2 className="card-title">Money in and out by month (₹ lakh)</h2>
            <EChart key={props.dark ? 'dark' : 'light'} option={monthly(flow, colours)} dark={props.dark} height={300} />
          </section>
        </div>
        <section className="card" aria-label="By what it was for">
          <ExplorerTable id="cash-movements" label="Cash movement by what it was for" columns={COLUMNS} rows={flow.movements} rowKey={(m) => m.key} totalLabel="Total" />
          <p className="card-note">The full cash flow statement (operating, investing, financing) is planned separately: it needs every ledger classified.</p>
        </section>
        {flow.combined && <Typography.Text type="secondary">Several companies combined, without inter-company eliminations.</Typography.Text>}
      </>
    )
  }
  return (
    <ReportFrame {...props} title="Cash movement" page="cash-flow" period={undefined} combined={flow?.combined ?? false} help={help}>
      {content}
    </ReportFrame>
  )
}
