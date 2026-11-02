import { describe, expect, it } from 'vitest'
import type { Home } from '../../api/types.ts'
import { tokens } from '../../theme.ts'
import { salesAndPurchases } from './homeChart.ts'

const month = (m: string, gross: string | null, net: string | null) => ({ month: m, sales: '8000000', purchases: '5000000', gross_profit: gross, net_profit: net })

describe('the sales and purchases chart', () => {
  const home = { monthly: [month('2026-04-01', '2500000', '-400000'), month('2026-05-01', null, null)] } as Home
  const option = salesAndPurchases(home, tokens.light)
  const series = option.series as { type: string; name: string; data: (number | null)[] }[]

  it('marks each month\'s gross and net profit as lines over the bars, in lakhs', () => {
    expect(series.map((s) => [s.type, s.name])).toEqual([
      ['bar', 'Sales'],
      ['bar', 'Purchases'],
      ['line', 'Gross profit'],
      ['line', 'Net profit'],
    ])
    expect(series[2].data).toEqual([25, null]) // a gap where a month has no statement
    expect(series[3].data).toEqual([-4, null]) // a loss below the axis
  })

  it('shows the profit in the tooltip, or a dash', () => {
    const tooltip = option.tooltip as { formatter: (p: unknown) => string }
    expect(tooltip.formatter([{ dataIndex: 0 }])).toContain('Net profit -₹4,00,000.00')
    expect(tooltip.formatter([{ dataIndex: 1 }])).toContain('Gross profit —')
  })
})
