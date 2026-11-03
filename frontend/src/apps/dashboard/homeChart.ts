// The Dashboard's sales and purchases chart (docs/design/dashboard.md Section 0.1, screen 5):
// the months' sales and purchases as bars, and each month's gross and net profit (from the
// stored statements; docs/formulas.md) as marked lines, with a gap where a month has none.

import type { EChartsOption } from 'echarts'
import type { Home } from '../../api/types.ts'
import { formatExact, formatMonth, toLakhs } from '../../format.ts'
import type { Tokens } from '../../theme.ts'

const orDash = (amount: string | null) => (amount === null ? '—' : formatExact(amount))

/** Sales and purchases as bars, each month's gross and net profit as marked lines (a gap
 *  where a month has no stored statement). */
export function salesAndPurchases(home: Home, colours: Tokens): EChartsOption {
  const months = home.monthly
  const text = colours.muted
  const line = (name: string, colour: string, values: (string | null)[], dashed: boolean) => ({
    type: 'line' as const,
    name,
    data: values.map((v) => (v === null ? null : toLakhs(v))),
    symbol: 'circle',
    symbolSize: 8,
    lineStyle: { color: colour, width: 2, type: dashed ? ('dashed' as const) : ('solid' as const) },
    itemStyle: { color: colour },
    z: 3,
  })
  return {
    backgroundColor: 'transparent',
    grid: { left: 48, right: 8, top: 16, bottom: 28 },
    tooltip: {
      trigger: 'axis',
      formatter: (params: unknown) => {
        const [first] = params as { dataIndex: number }[]
        const m = months[first.dataIndex]
        return [
          formatMonth(m.month),
          `Sales ${formatExact(m.sales)}`,
          `Purchases ${formatExact(m.purchases)}`,
          `Gross profit ${orDash(m.gross_profit)}`,
          `Net profit ${orDash(m.net_profit)}`,
        ].join('<br/>')
      },
    },
    xAxis: { type: 'category', data: months.map((m) => formatMonth(m.month).slice(0, 3)), axisLabel: { color: text } },
    yAxis: { type: 'value', axisLabel: { color: text }, splitLine: { lineStyle: { color: colours.border } } },
    series: [
      { type: 'bar', name: 'Sales', data: months.map((m) => toLakhs(m.sales)), itemStyle: { color: colours.primary } },
      { type: 'bar', name: 'Purchases', data: months.map((m) => toLakhs(m.purchases)), itemStyle: { color: colours.neutralBar } },
      line('Gross profit', colours.grossProfit, months.map((m) => m.gross_profit), false),
      line('Net profit', colours.netProfit, months.map((m) => m.net_profit), true),
    ],
  }
}

/** The P&L page's monthly trend: net sales as bars, gross and net profit as marked lines. */
export function profitTrend(home: Home, colours: Tokens): EChartsOption {
  const option = salesAndPurchases(home, colours)
  const series = (option.series as { name: string }[]).filter((s) => s.name !== 'Purchases')
  return { ...option, series } as EChartsOption
}
