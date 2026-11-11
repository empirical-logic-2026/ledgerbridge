// A donut for a mix (docs/design/dashboard.md Section 0.4): the parts as a ring with the total
// in the middle, and beside it the legend as plain markup (each part's name, short amount and
// share; a part opens its page when it has one). Shares are worked out from exact amounts.

import type { EChartsOption } from 'echarts'
import { formatAmount, useAmountFormat } from '../amountFormat.ts'
import { formatExact, toLakhs, toScaled } from '../format.ts'
import { Money } from './Money.tsx'
import { fromScaled } from '../reporting/explorer.ts'
import { shares, type DonutPart } from './shares.ts'
import { EChart } from './EChart.tsx'

interface Props {
  label: string
  parts: DonutPart[]
  colours: string[]
  dark: boolean
  formula: string // the parts' formula ID (docs/formula-sheet.md)
}

function ring(parts: DonutPart[], colours: string[], total: string): EChartsOption {
  return {
    backgroundColor: 'transparent',
    tooltip: { trigger: 'item', formatter: (p: unknown) => `${(p as { name: string }).name}: ${formatExact(parts[(p as { dataIndex: number }).dataIndex].amount)}` },
    title: { text: total, left: 'center', top: 'center', textStyle: { fontSize: 13, fontWeight: 600 } },
    series: [{
      type: 'pie',
      radius: ['55%', '85%'],
      label: { show: false },
      data: parts.map((p, i) => ({ name: p.name, value: Math.max(0, toLakhs(p.amount)), itemStyle: { color: colours[i % colours.length] } })),
    }],
  }
}

export function Donut({ label, parts, colours, dark, formula }: Props) {
  const { format } = useAmountFormat()
  const share = shares(parts)
  const total = parts.reduce((sum, p) => sum + toScaled(p.amount), 0n)
  const totalText = formatAmount(fromScaled(total), format)
  return (
    <div className="donut" aria-label={label} role="group" data-figure="donut" data-formula={formula}>
      <div className="donut-ring">
        <EChart key={dark ? 'dark' : 'light'} option={ring(parts, colours, totalText)} dark={dark} height={150} />
      </div>
      <ul className="donut-legend">
        {parts.map((p, i) => (
          <li key={p.name}>
            <span className="legend-key" style={{ background: colours[i % colours.length] }} />
            {p.to ? <a href={p.to}>{p.name}</a> : <span>{p.name}</span>}
            <Money value={p.amount} className="donut-amount" />
            <span className="donut-share">{share[i]}%</span>
          </li>
        ))}
      </ul>
    </div>
  )
}
