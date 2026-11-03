// A waterfall for cash (docs/design/dashboard.md Section 0.4): the opening and closing as whole
// bars, each movement floating from the running total, money in green and out crimson. The bars:
// waterfall.ts; amounts in ₹ lakh for drawing, exact on hover.

import type { EChartsOption } from 'echarts'
import { formatExact } from '../format.ts'
import type { Tokens } from '../theme.ts'
import { EChart } from './EChart.tsx'
import { waterfallBars, type Step } from './waterfall.ts'

function option(steps: Step[], colours: Tokens): EChartsOption {
  const bars = waterfallBars(steps)
  const colour = { total: colours.grossProfit, up: colours.primary, down: colours.negative }
  return {
    backgroundColor: 'transparent',
    grid: { left: 52, right: 8, top: 16, bottom: 48 },
    tooltip: {
      trigger: 'axis',
      formatter: (params: unknown) => {
        const bar = bars[(params as { dataIndex: number }[])[0].dataIndex]
        return `${bar.label}<br/>${formatExact(bar.amount)}`
      },
    },
    xAxis: { type: 'category', data: bars.map((b) => b.label), axisLabel: { color: colours.muted, interval: 0, rotate: 30 } },
    yAxis: { type: 'value', axisLabel: { color: colours.muted }, splitLine: { lineStyle: { color: colours.border } } },
    series: [
      { type: 'bar', stack: 'flow', data: bars.map((b) => b.base), itemStyle: { color: 'transparent' }, emphasis: { disabled: true } },
      { type: 'bar', stack: 'flow', data: bars.map((b) => ({ value: b.height, itemStyle: { color: colour[b.kind] } })) },
    ],
  }
}

export function Waterfall({ steps, colours, dark }: { steps: Step[]; colours: Tokens; dark: boolean }) {
  return <EChart key={dark ? 'dark' : 'light'} option={option(steps, colours)} dark={dark} height={300} />
}
