// ECharts options for monthly net sales by selected entity, with the existing sales breakdown on hover.

import type { EChartsOption } from 'echarts'
import type { Company, CompanyMonthSales } from '../../api/types.ts'
import { companyDisplayName } from '../../companyDisplayName.ts'
import { formatExact, formatMonth, toLakhs } from '../../format.ts'
import type { Tokens } from '../../theme.ts'

interface Series {
  company: Company
  months: Map<string, CompanyMonthSales>
}

const LINE_STYLES: Array<'solid' | 'dashed' | 'dotted'> = ['solid', 'dashed', 'dotted']

function escapeTooltip(text: string): string {
  return text.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&#39;')
}

export function branchSalesChart(
  rows: CompanyMonthSales[],
  companies: Company[],
  colours: Tokens,
): EChartsOption {
  const months = [...new Set(rows.map((row) => row.month))].sort()
  const rowsByCompany = new Map<number, Map<string, CompanyMonthSales>>()
  for (const row of rows) {
    const companyRows = rowsByCompany.get(row.company) ?? new Map<string, CompanyMonthSales>()
    companyRows.set(row.month, row)
    rowsByCompany.set(row.company, companyRows)
  }
  const series: Series[] = companies
    .filter((company) => rowsByCompany.has(company.id))
    .map((company) => ({ company, months: rowsByCompany.get(company.id) ?? new Map() }))
  const palette = [colours.primary, colours.grossProfit, colours.netProfit, colours.neutralBar, colours.positive, colours.muted]

  return {
    backgroundColor: 'transparent',
    color: palette,
    grid: { left: 58, right: 16, top: 44, bottom: months.length > 8 ? 58 : 36 },
    legend: {
      type: 'scroll',
      top: 0,
      textStyle: { color: colours.muted },
    },
    tooltip: {
      trigger: 'item',
      formatter: (param: unknown) => {
        const point = param as { dataIndex?: number; seriesIndex?: number }
        const item = series[point.seriesIndex ?? -1]
        const row = item?.months.get(months[point.dataIndex ?? -1] ?? '')
        if (!item || !row) return ''
        const name = escapeTooltip(companyDisplayName(item.company))
        return [
          name,
          escapeTooltip(formatMonth(row.month)),
          `Net sales: ${escapeTooltip(formatExact(row.net))}`,
          `Gross sales: ${escapeTooltip(formatExact(row.gross))}`,
          `Sales returns: ${escapeTooltip(formatExact(row.returns))}`,
          `Other adjustments: ${escapeTooltip(formatExact(row.other))}`,
        ].join('<br/>')
      },
    },
    xAxis: {
      type: 'category',
      data: months.map(formatMonth),
      axisLabel: { color: colours.muted, rotate: months.length > 8 ? 30 : 0 },
      axisLine: { lineStyle: { color: colours.border } },
    },
    yAxis: {
      type: 'value',
      name: '₹ lakh',
      nameTextStyle: { color: colours.muted },
      axisLabel: { color: colours.muted },
      splitLine: { lineStyle: { color: colours.border } },
    },
    series: series.map((item, index) => ({
      type: 'line',
      name: companyDisplayName(item.company),
      data: months.map((month) => {
        const row = item.months.get(month)
        return row ? toLakhs(row.net) : null
      }),
      connectNulls: false,
      showSymbol: true,
      symbolSize: 6,
      itemStyle: { color: palette[index % palette.length] },
      lineStyle: {
        color: palette[index % palette.length],
        width: 2,
        type: LINE_STYLES[Math.floor(index / palette.length) % LINE_STYLES.length],
      },
      emphasis: { focus: 'series' },
    })),
  }
}
