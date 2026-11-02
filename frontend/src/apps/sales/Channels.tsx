// Sales by channel (docs/design/dashboard.md Section 0.2): each voucher type of sales with its
// net sales, share, gross, returns and invoices, and its net sales month by month (a column per
// month); a channel opens the Sales register filtered to it, and a month that month's.
// Figures: core/sales.py (GET /api/v1/sales/channels).

import { Alert, Skeleton } from 'antd'
import type { EChartsOption } from 'echarts'
import type { ChannelOut, ChannelsOut, Company } from '../../api/types.ts'
import { EChart } from '../../components/EChart.tsx'
import { formatExact, formatMonth, toLakhs } from '../../format.ts'
import type { ExplorerColumn } from '../../reporting/explorer.ts'
import { ExplorerTable } from '../../reporting/ExplorerTable.tsx'
import { ReportFrame, type PanelProps } from '../../reporting/ReportFrame.tsx'
import type { Query } from '../../router.ts'
import { builtHref } from '../../shell/nav.ts'
import { tokens, type Tokens } from '../../theme.ts'

interface Props extends PanelProps {
  companies: Company[]
  channels: ChannelsOut | undefined
  loading: boolean
  error: Error | null
  dark: boolean
}

function registerHref(query: Query, channel: string, month?: string): string | undefined {
  const asked = month ? { ...query, channel: [channel], month: month.slice(0, 7), from: undefined, to: undefined } : { ...query, channel: [channel] }
  return builtHref(['sales', 'register'], asked)
}

function columns(found: ChannelsOut, query: Query): ExplorerColumn<ChannelOut>[] {
  const months = found.channels[0]?.months.map((m) => m.month) ?? []
  return [
    { key: 'name', label: 'Channel (voucher type)', kind: 'text', value: (c) => c.name, link: (c) => registerHref(query, c.name) },
    { key: 'net', label: 'Net sales', kind: 'amount', value: (c) => c.net },
    { key: 'share', label: 'Share', kind: 'text', value: (c) => (c.share_pct === null ? null : `${c.share_pct}%`) },
    { key: 'gross', label: 'Gross', kind: 'amount', value: (c) => c.gross, hidden: true },
    { key: 'returns', label: 'Returns', kind: 'amount', value: (c) => c.returns },
    { key: 'other', label: 'Other adjustments', kind: 'amount', value: (c) => c.other, hidden: true },
    { key: 'invoices', label: 'Invoices', kind: 'count', value: (c) => c.invoices },
    ...months.map(
      (month, i): ExplorerColumn<ChannelOut> => ({
        key: `m-${month}`,
        label: formatMonth(month).slice(0, 3),
        kind: 'amount',
        value: (c) => c.months[i]?.net ?? null,
        link: (c) => registerHref(query, c.name, month),
        hidden: months.length > 6,
      }),
    ),
  ]
}

function chart(found: ChannelsOut, colours: Tokens): EChartsOption {
  const rows = [...found.channels].reverse() // the largest at the top
  return {
    backgroundColor: 'transparent',
    grid: { left: 140, right: 24, top: 8, bottom: 24 },
    tooltip: { trigger: 'axis', formatter: (params: unknown) => {
      const [first] = params as { dataIndex: number }[]
      const c = rows[first.dataIndex]
      return `${c.name}<br/>Net sales ${formatExact(c.net)}`
    } },
    xAxis: { type: 'value', axisLabel: { color: colours.muted }, splitLine: { lineStyle: { color: colours.border } } },
    yAxis: { type: 'category', data: rows.map((c) => c.name), axisLabel: { color: colours.muted, width: 130, overflow: 'truncate' } },
    series: [{ type: 'bar', name: 'Net sales', data: rows.map((c) => toLakhs(c.net)), itemStyle: { color: colours.primary } }],
  }
}

function Help(sourceName: string) {
  return (
    <>
      <p>
        Net sales by channel: each voucher type of sales (for example Sales, Online Sales, Export Sales) with what its vouchers put on the ledgers under{' '}
        {sourceName}'s Sales Accounts group, including the credit notes and journals of that type. Types of the same name in several companies are
        added together.
      </p>
      <p>
        <strong>Where the figures come from:</strong> the books, the same figures as the monthly sales views by voucher type, proven day by day against{' '}
        {sourceName}'s statements. All channels together are the net sales of the Sales dashboard.
      </p>
      <p>
        <strong>To compare with {sourceName}:</strong> open the Sales Register (Display More Reports → Account Books) for that voucher type; its monthly
        totals are the gross figures here, and the Credit Note Register the returns.
      </p>
    </>
  )
}

export function Channels(props: Props) {
  const found = props.channels
  const colours = tokens[props.dark ? 'dark' : 'light']
  let content: React.ReactNode
  if (props.error) {
    content = <Alert type="error" showIcon message="The channels couldn't be loaded." description={props.error.message} />
  } else if (props.loading || !found) {
    content = <Skeleton active paragraph={{ rows: 10 }} />
  } else {
    content = (
      <section className="card" aria-label="Net sales by channel">
        {found.channels.length > 0 && (
          <EChart
            key={props.dark ? 'dark' : 'light'}
            option={chart(found, colours)}
            dark={props.dark}
            height={Math.max(160, 36 * found.channels.length)}
            onClick={(i) => {
              const c = [...found.channels].reverse()[i]
              const to = c && registerHref(props.query, c.name)
              if (to) window.location.hash = to.slice(1)
            }}
          />
        )}
        <ExplorerTable id="sales-channels" label="Sales by channel" columns={columns(found, props.query)} rows={found.channels} rowKey={(c) => c.name} sortKey="net" descending totalLabel="Total" />
      </section>
    )
  }
  return (
    <ReportFrame {...props} title="Sales by channel" page="sales-channels" period={found?.period} combined={found?.combined ?? false} help={Help}>
      {content}
    </ReportFrame>
  )
}
