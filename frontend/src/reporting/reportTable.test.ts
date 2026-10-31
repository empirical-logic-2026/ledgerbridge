import { describe, expect, it } from 'vitest'
import type { StatementReport } from '../api/types.ts'
import { buildCsv, cellValue, formatCell, optionsQuery, readOptions, shownColumns, shownLines, unitFor } from './reportTable.ts'

const line = (label: string, level: 'main' | 'sub' | 'detail', a: string | null, b: string | null, last: string | null, change: string | null) => ({
  key: label.toLowerCase(),
  label,
  level,
  section: 'gross',
  higher_is_better: true,
  values: { 'company:3': a, 'company:4': b, total: a && b ? String(Number(a) + Number(b)) : null, last_year: last },
  pct_of_sales: { 'company:3': '50.0', 'company:4': '50.0', total: '50.0', last_year: null },
  change_pct: change,
})

const report: StatementReport = {
  companies: [3, 4],
  combined: true,
  view: 'company',
  period_start: '2026-04-01',
  period_end: '2026-09-30',
  columns: [
    { key: 'company:3', label: 'Alpha', kind: 'company' },
    { key: 'company:4', label: 'Beta', kind: 'company' },
    { key: 'total', label: 'Total', kind: 'total' },
    { key: 'last_year', label: 'Last year', kind: 'last_year' },
  ],
  lines: [
    line('Sales Accounts', 'main', '341260000.0000', '41030000.0000', '340100000', '12.0'),
    line('Opening Stock', 'sub', '0', '0', '0', null),
    line('Net Profit', 'detail', '-5000.5', '200', null, null),
  ],
  reason: null,
  shifted: false,
  last_year_reason: null,
  matching: { matches: true, dates: ['2026-09-30'], differing: 0, compared: 12, unchecked: 0 },
}

describe('report options', () => {
  it('default to company by company with each, total, last year and change', () => {
    const o = readOptions(new URLSearchParams(''))
    expect(o).toEqual({ view: 'company', asPercent: false, columns: ['each', 'total', 'last', 'change'], showSub: true, hideZero: false })
    expect(optionsQuery(o)).toEqual({ view: undefined, pct: undefined, col: undefined, sub: undefined, zero: undefined })
  })

  it('round-trip through the URL', () => {
    const o = readOptions(new URLSearchParams('view=month&pct=1&col=total&col=pct&col=bogus&sub=0&zero=0'))
    expect(o).toEqual({ view: 'month', asPercent: true, columns: ['total', 'pct'], showSub: false, hideZero: true })
    expect(readOptions(new URLSearchParams(new URLSearchParams(Object.entries(optionsQuery(o)).flatMap(([k, v]) => (Array.isArray(v) ? v.map((x) => [k, x]) : v ? [[k, v]] : []))).toString()))).toEqual(o)
    expect(readOptions(new URLSearchParams('col=none')).columns).toEqual([]) // every column off
  })
})

describe('the table', () => {
  const o = readOptions(new URLSearchParams(''))

  it('shows each company, the total, last year and the change', () => {
    expect(shownColumns(report, o).map((c) => c.key)).toEqual(['company:3', 'company:4', 'total', 'last_year', 'change'])
    expect(cellValue(report.lines[0], shownColumns(report, o)[4])).toBe('12.0')
  })

  it('leaves out a single company\'s column, which would repeat the total', () => {
    const one = { ...report, companies: [3], columns: [report.columns[0], report.columns[2]] }
    expect(shownColumns(one, o).map((c) => c.key)).toEqual(['total'])
  })

  it('shows every amount as % of sales when asked', () => {
    const pct = shownColumns(report, { ...o, asPercent: true })
    expect(pct.every((c) => c.kind !== 'amount')).toBe(true)
    expect(cellValue(report.lines[0], pct[0])).toBe('50.0')
  })

  it('filters the lines inside blocks and the zero lines', () => {
    expect(shownLines(report, { ...o, showSub: false }).map((l) => l.label)).toEqual(['Sales Accounts', 'Net Profit'])
    expect(shownLines(report, { ...o, hideZero: true }).map((l) => l.label)).toEqual(['Sales Accounts', 'Net Profit'])
  })

  it('writes amounts in lakh when they are large, else in rupees', () => {
    expect(unitFor(report)).toBe('lakh')
    expect(formatCell('341260000.0000', 'lakh')).toBe('3,412.6')
    expect(formatCell('33100', 'rupees')).toBe('33,100')
    expect(formatCell('-5000.5', 'rupees')).toBe('-5,001')
    expect(unitFor({ ...report, lines: [report.lines[2]] })).toBe('rupees')
  })

  it('exports exactly the table on screen as CSV, exact rupees, formulas guarded', () => {
    const csv = buildCsv({ ...report, lines: [...report.lines, line('=HYPERLINK("x")', 'main', '1', '2', null, null)] }, o)
    const rows = csv.trim().split('\r\n')
    expect(rows[0]).toBe('Particulars,Alpha (₹),Beta (₹),Total (₹),Last year (₹),Change (%)')
    expect(rows[1]).toBe('Sales Accounts,341260000.00,41030000.00,382290000.00,340100000.00,12.0')
    expect(rows[2]).toBe('  Opening Stock,0.00,0.00,0.00,0.00,')
    expect(rows[3]).toBe('Net Profit,-5000.50,200.00,-4800.50,,')
    expect(rows[4].startsWith(`"'=HYPERLINK(""x"")"`)).toBe(true)
    expect(buildCsv(report, { ...o, showSub: false })).not.toContain('Opening Stock')
  })
})
