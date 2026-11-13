// What the user is looking at (docs/design/dashboard.md Sections 0.1, 0.2 and 0.4): any
// combination of companies (none chosen = all, combined), the period toggle (MTD, QTD, YTD, the
// financial year, or Custom: whole months, one or several, adjacent or not, or a from/to date
// range), what to compare with (the previous period, last year, or nothing: RPT-016, formula
// F-CMP-002), and the facets (customers, channels, ledger groups, voucher types, by name). Kept
// in the URL's query, so a view can be bookmarked, shared with Copy link, and the back button
// works.

import type { Company, ComparedWith, FinancialYear, Periods } from './api/types.ts'
import { formatDate } from './format.ts'
import { updateQuery, useRoute } from './router.ts'
import type { Facet } from './shell/nav.ts'

export type Toggle = 'mtd' | 'qtd' | 'ytd' | 'fy' | 'custom'
export type CompareKind = 'previous' | 'last_year' | 'none'
export type Span = 'month' | 'quarter' | 'year' // what a "to date" period runs over

export const TOGGLES: { key: Toggle; label: string; title: string }[] = [
  { key: 'mtd', label: 'MTD', title: 'Month to date' },
  { key: 'qtd', label: 'QTD', title: 'Quarter to date (quarters of the financial year)' },
  { key: 'ytd', label: 'YTD', title: 'Financial year to date' },
  { key: 'fy', label: 'FY', title: 'The whole financial year chosen' },
  { key: 'custom', label: 'Custom', title: 'Months or dates of your choice' },
]

export interface Selection {
  companies: number[] // empty: all of them, combined
  fy: number | undefined
  toggle: Toggle
  months: string[] // "2026-04" (Custom)
  from: string | undefined // "2026-04-01" (Custom)
  to: string | undefined
  compare: CompareKind
  facets: Record<Facet, string[]> // names; empty: all
}

export type Change = (change: Partial<Selection>) => void

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/
const MONTH = /^\d{4}-\d{2}$/

export function readSelection(query: URLSearchParams): Selection {
  const fy = query.get('fy')
  const from = query.get('from') ?? undefined
  const to = query.get('to') ?? undefined
  const months = query.getAll('month').filter((m) => MONTH.test(m))
  const dates = from && ISO_DATE.test(from) && to && ISO_DATE.test(to)
  return {
    companies: query.getAll('company').filter((c) => /^\d+$/.test(c)).map(Number),
    fy: fy && /^\d{4}$/.test(fy) ? Number(fy) : undefined,
    toggle: readToggle(query.get('p'), months.length > 0 || !!dates),
    months,
    from: from && ISO_DATE.test(from) ? from : undefined,
    to: to && ISO_DATE.test(to) ? to : undefined,
    compare: readCompare(query.get('compare')),
    facets: {
      customer: query.getAll('customer'),
      channel: query.getAll('channel'),
      ledger_group: query.getAll('group'),
      voucher_type: query.getAll('vtype'),
    },
  }
}

/** The toggle asked for; links made before the toggles (months or dates given) are Custom, and
 *  the default is the financial year to date. */
function readToggle(value: string | null, chosen: boolean): Toggle {
  const found = TOGGLES.find((t) => t.key === value)
  if (found) return found.key
  return chosen ? 'custom' : 'ytd'
}

/** The previous period unless asked otherwise; "0" (off) and "1" (last year) are older links'. */
function readCompare(value: string | null): CompareKind {
  if (value === '0' || value === 'none') return 'none'
  if (value === 'last_year' || value === '1') return 'last_year'
  return 'previous'
}

/** The selection as URL query values (repeated keys for lists). */
export function selectionQuery(s: Selection): Record<string, string | string[] | undefined> {
  return {
    company: s.companies.map(String),
    fy: s.fy === undefined ? undefined : String(s.fy),
    p: s.toggle === 'ytd' ? undefined : s.toggle,
    month: s.toggle === 'custom' ? s.months : [],
    from: s.toggle === 'custom' ? s.from : undefined,
    to: s.toggle === 'custom' ? s.to : undefined,
    compare: s.compare === 'previous' ? undefined : s.compare,
    customer: s.facets.customer,
    channel: s.facets.channel,
    group: s.facets.ledger_group,
    vtype: s.facets.voucher_type,
  }
}

export function useSelection(): [Selection, Change] {
  const route = useRoute()
  const selection = readSelection(route.query)
  const change: Change = (next) => updateQuery(route, selectionQuery({ ...selection, ...next }))
  return [selection, change]
}

/** The company ids the selection covers (every visible company when none is chosen). */
export function selectedIds(selection: Selection, companies: Company[] | undefined): number[] | undefined {
  if (!companies) return undefined
  const chosen = companies.filter((c) => selection.companies.includes(c.id)).map((c) => c.id)
  return chosen.length ? chosen : companies.map((c) => c.id)
}

/** The year asked for, else the latest one. */
export function chosenYear(selection: Selection, periods: Periods | undefined): FinancialYear | undefined {
  const years = periods?.financial_years ?? []
  return years.find((y) => y.start_year === selection.fy) ?? years[0]
}

/** "2026-09" -> "2026-09-30". */
export function monthEnd(month: string): string {
  const [y, m] = month.split('-').map(Number)
  const day = new Date(Date.UTC(y, m, 0)).getUTCDate()
  return `${month}-${String(day).padStart(2, '0')}`
}

/** The first and last day a period covers. */
export function periodDates(period: PeriodChoice): [string, string] {
  if (!period.months.length) return [period.from ?? '', period.to ?? '']
  const sorted = [...period.months].sort()
  return [`${sorted[0]}-01`, monthEnd(sorted[sorted.length - 1])]
}

/** The year's twelve months, "2026-04" to "2027-03". */
export function yearMonths(year: FinancialYear): string[] {
  const months: string[] = []
  let [y, m] = year.start.split('-').map(Number)
  for (let i = 0; i < 12; i++) {
    months.push(`${y}-${String(m).padStart(2, '0')}`)
    m += 1
    if (m > 12) {
      m = 1
      y += 1
    }
  }
  return months
}

export interface PeriodChoice {
  months: string[] // empty for a date range
  from?: string
  to?: string
  span?: Span // MTD: month, QTD: quarter, YTD and FY: year; Custom: none
}

/** The period to show (RPT-016):
 *  - MTD, QTD and YTD run from the start of today's month, quarter or financial year to today
 *    (the financial year that holds today; its quarters start with its first month);
 *  - FY: the twelve months of the financial year chosen;
 *  - Custom: the dates given, else the months asked for inside the year, else the year's months
 *    up to this month. */
export function chosenPeriod(selection: Selection, year: FinancialYear | undefined, today: string, years: FinancialYear[] = []): PeriodChoice | undefined {
  if (!year) return undefined
  const current = years.find((y) => y.start <= today && today <= y.end) ?? year
  switch (selection.toggle) {
    case 'mtd':
      return { months: [], from: `${today.slice(0, 7)}-01`, to: today, span: 'month' }
    case 'qtd':
      return { months: [], from: quarterStart(current, today), to: today, span: 'quarter' }
    case 'ytd':
      return { months: [], from: current.start, to: today < current.end ? today : current.end, span: 'year' }
    case 'fy':
      return { months: yearMonths(year), span: 'year' }
  }
  if (selection.from && selection.to && selection.from <= selection.to) {
    return { months: [], from: selection.from, to: selection.to }
  }
  const all = yearMonths(year)
  const asked = selection.months.filter((m) => all.includes(m))
  if (asked.length) return { months: asked }
  const upToNow = all.filter((m) => m <= today.slice(0, 7))
  return { months: upToNow.length ? upToNow : all }
}

/** The first day of the quarter of the financial year that holds the day. */
export function quarterStart(year: FinancialYear, day: string): string {
  const months = yearMonths(year)
  const index = Math.max(0, months.indexOf(day.slice(0, 7)))
  return `${months[index - (index % 3)]}-01`
}

/** The comparison as the API's query: `compare` and, for a "to date" period, its `span`. */
export function comparisonQuery(compare: CompareKind, period: PeriodChoice | undefined): { compare: CompareKind; span?: Span } {
  return compare === 'previous' ? { compare, span: period?.span } : { compare }
}

export const COMPARE_OPTIONS: { value: CompareKind; label: string }[] = [
  { value: 'previous', label: 'vs previous period' },
  { value: 'last_year', label: 'vs last year' },
  { value: 'none', label: 'No comparison' },
]

/** "01-Apr-2026 to 02-Nov-2026 · vs previous period": the page header's period line. */
export function periodText(period: PeriodChoice | undefined, selection: Selection): string {
  if (!period) return ''
  const [from, to] = periodDates(period)
  const compare = COMPARE_OPTIONS.find((o) => o.value === selection.compare)
  const months = period.months.length > 1 && period.span !== 'year' ? ` (${period.months.length} months)` : ''
  return `${formatDate(from)} to ${formatDate(to)}${months}${selection.compare === 'none' ? '' : ` · ${compare?.label}`}`
}

/** What a response's figures are compared with: its name ("previous period", "last year",
 *  "previous period (same dates last year)" for YTD and FY) and its dates ("01-Sep-2026 to
 *  30-Sep-2026"); none when nothing was compared (F-CMP-002, ADR-057). */
export interface Against {
  label: string
  dates: string
}

export function againstOf(compared: ComparedWith | null | undefined): Against | undefined {
  return compared ? { label: compared.label.toLowerCase(), dates: comparedDates(compared) } : undefined
}

/** "01-Sep-2026 to 30-Sep-2026": the dates a comparison covers. */
export function comparedDates(compared: ComparedWith): string {
  return `${formatDate(compared.start)} to ${formatDate(compared.end)}`
}
