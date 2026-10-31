// What a statement report page shows (docs/design/dashboard.md Section 0.1, screen 6): the
// options read from the URL (view as, columns, filters), the visible columns, the amount unit,
// and the CSV of exactly the table on screen. Pure functions: tested in reportTable.test.ts.

import type { LineOut, StatementReport } from '../api/types.ts'
import { indianGrouping, toScaled } from '../format.ts'

export type View = 'company' | 'month' | 'quarter'
export type ColumnChoice = 'each' | 'total' | 'last' | 'change' | 'pct'

export const COLUMN_CHOICES: { key: ColumnChoice; label: string }[] = [
  { key: 'each', label: 'Each column' }, // each company, month or quarter
  { key: 'total', label: 'Total' },
  { key: 'last', label: 'Last year' },
  { key: 'change', label: 'Change %' },
  { key: 'pct', label: '% of sales' },
]
const DEFAULT_COLUMNS: ColumnChoice[] = ['each', 'total', 'last', 'change']

export interface ReportOptions {
  view: View
  asPercent: boolean // "As % of sales": every amount as a percentage of its column's net sales
  columns: ColumnChoice[]
  showSub: boolean // the lines inside blocks (e.g. Opening Stock in Cost of Sales)
  hideZero: boolean
}

export function readOptions(query: URLSearchParams): ReportOptions {
  const view = query.get('view')
  const chosen = query.getAll('col').filter((c): c is ColumnChoice => COLUMN_CHOICES.some((x) => x.key === c))
  return {
    view: view === 'month' || view === 'quarter' ? view : 'company',
    asPercent: query.get('pct') === '1',
    columns: query.has('col') ? chosen : DEFAULT_COLUMNS,
    showSub: query.get('sub') !== '0',
    hideZero: query.get('zero') === '0',
  }
}

/** The options as URL query values (defaults left out). */
export function optionsQuery(o: ReportOptions): Record<string, string | string[] | undefined> {
  const columns = [...o.columns].sort().join() === [...DEFAULT_COLUMNS].sort().join() ? undefined : o.columns.length ? o.columns : ['none']
  return {
    view: o.view === 'company' ? undefined : o.view,
    pct: o.asPercent ? '1' : undefined,
    col: columns,
    sub: o.showSub ? undefined : '0',
    zero: o.hideZero ? '0' : undefined,
  }
}

export interface ShownColumn {
  key: string // unique in the table
  label: string
  source: string // the report column it reads
  kind: 'amount' | 'change' | 'pct'
}

export function shownColumns(report: StatementReport, o: ReportOptions): ShownColumn[] {
  const shown: ShownColumn[] = []
  for (const c of report.columns) {
    const amount: ShownColumn = { key: c.key, label: c.label, source: c.key, kind: o.asPercent ? 'pct' : 'amount' }
    if (c.kind === 'total') {
      if (o.columns.includes('total')) shown.push(amount)
      if (o.columns.includes('pct') && !o.asPercent) shown.push({ key: 'total:pct', label: '% of sales', source: 'total', kind: 'pct' })
    } else if (c.kind === 'last_year') {
      if (o.columns.includes('last')) shown.push(amount)
      if (o.columns.includes('change')) shown.push({ key: 'change', label: 'Change', source: 'total', kind: 'change' })
    } else if (o.columns.includes('each')) {
      const onlyCompany = c.kind === 'company' && report.companies.length === 1
      if (!(onlyCompany && o.columns.includes('total'))) shown.push(amount) // else it repeats the total
    }
  }
  return shown
}

export function shownLines(report: StatementReport, o: ReportOptions): LineOut[] {
  return report.lines.filter((line) => {
    if (line.level === 'sub' && !o.showSub) return false
    if (o.hideZero && Object.values(line.values).every((v) => v === null || toScaled(v) === 0n)) return false
    return true
  })
}

export function cellValue(line: LineOut, column: ShownColumn): string | null {
  if (column.kind === 'change') return line.change_pct
  if (column.kind === 'pct') return line.pct_of_sales[column.source] ?? null
  return line.values[column.source] ?? null
}

export type Unit = 'rupees' | 'lakh'

/** ₹ lakh when the largest amount shown is at least ₹10 lakh, else rupees. */
export function unitFor(report: StatementReport): Unit {
  const largest = report.lines
    .flatMap((l) => Object.values(l.values))
    .reduce((max, v) => {
      if (v === null) return max
      const size = toScaled(v) < 0n ? -toScaled(v) : toScaled(v)
      return size > max ? size : max
    }, 0n)
  return largest >= 10n ** 6n * 10n ** 4n ? 'lakh' : 'rupees'
}

/** An amount in the table: "3,412.6" in lakh (one decimal) or "33,100" in rupees. */
export function formatCell(value: string, unit: Unit): string {
  const scaled = toScaled(value)
  const negative = scaled < 0n
  const size = negative ? -scaled : scaled
  let text: string
  if (unit === 'lakh') {
    const tenths = (size + 5n * 10n ** 7n) / 10n ** 8n // 1 lakh = 10^5 rupees = 10^9 units; tenths
    text = `${indianGrouping((tenths / 10n).toString())}.${tenths % 10n}`
  } else {
    text = indianGrouping(((size + 5000n) / 10000n).toString())
  }
  return negative ? `-${text}` : text
}

/** The table on screen as CSV: the same lines and columns, exact amounts in rupees with two
 *  decimals (no grouping, for spreadsheets); text cells guarded against formulas. */
export function buildCsv(report: StatementReport, o: ReportOptions): string {
  const columns = shownColumns(report, o)
  const header = ['Particulars', ...columns.map((c) => (c.kind === 'amount' ? `${c.label} (₹)` : c.kind === 'pct' ? `${c.label} (%)` : `${c.label} (%)`))]
  const rows = shownLines(report, o).map((line) => [
    line.level === 'sub' ? `  ${line.label}` : line.label,
    ...columns.map((c) => {
      const v = cellValue(line, c)
      if (v === null) return ''
      return c.kind === 'amount' ? exactRupees(v) : v
    }),
  ])
  return [header, ...rows].map((row) => row.map(csvCell).join(',')).join('\r\n') + '\r\n'
}

function exactRupees(value: string): string {
  const scaled = toScaled(value)
  const negative = scaled < 0n
  const size = negative ? -scaled : scaled
  const paise = (size + 50n) / 100n
  return `${negative ? '-' : ''}${paise / 100n}.${String(paise % 100n).padStart(2, '0')}`
}

function csvCell(text: string): string {
  const safe = /^[=+\-@\t\r]/.test(text) && !/^-?\d/.test(text) ? `'${text}` : text
  return /[",\r\n]/.test(safe) ? `"${safe.replace(/"/g, '""')}"` : safe
}
