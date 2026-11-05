// Verifies that monthly company sales use the configured labels and the validated breakdown.

import { describe, expect, it } from 'vitest'
import type { Company, CompanyMonthSales } from '../../api/types.ts'
import { tokens } from '../../theme.ts'
import { branchSalesChart } from './branchSalesChart.ts'

const companies = [
  { id: 3, name: 'Original North Name', display_name: 'North' },
  { id: 4, name: 'Original South Name', display_name: 'South' },
] as Company[]

const rows: CompanyMonthSales[] = [
  { company: 4, month: '2026-05-01', gross: '110000', returns: '-10000', other: '0', net: '100000' },
  { company: 3, month: '2026-04-01', gross: '220000', returns: '-20000', other: '0', net: '200000' },
  { company: 3, month: '2026-05-01', gross: '330000', returns: '-30000', other: '0', net: '300000' },
  { company: 4, month: '2026-04-01', gross: '440000', returns: '-40000', other: '0', net: '400000' },
]

describe('the monthly sales by company chart', () => {
  const option = branchSalesChart(rows, companies, tokens.light)
  const series = option.series as { name: string; data: (number | null)[] }[]

  it('uses the selected entities, short display labels and month-wise net sales in lakhs', () => {
    expect(series.map((item) => item.name)).toEqual(['North', 'South'])
    expect(series.map((item) => item.data)).toEqual([[2, 3], [4, 1]])
    expect(option.xAxis).toMatchObject({ data: ['Apr-2026', 'May-2026'] })
    expect(option.legend).toMatchObject({ type: 'scroll' })
  })

  it('shows the same sales breakdown in each tooltip', () => {
    const tooltip = option.tooltip as { formatter: (point: unknown) => string }
    const content = tooltip.formatter({ seriesIndex: 0, dataIndex: 0 })
    expect(content).toContain('North')
    expect(content).toContain('Apr-2026')
    expect(content).toContain('Net sales: ₹2,00,000.00')
    expect(content).toContain('Gross sales: ₹2,20,000.00')
    expect(content).toContain('Sales returns: -₹20,000.00')
    expect(content).toContain('Other adjustments: ₹0.00')
  })
})
