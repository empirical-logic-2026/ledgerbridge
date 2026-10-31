// What the user is looking at (docs/design/dashboard.md Section 0.1): any combination of
// companies (none chosen = all, combined), the financial year, and either whole months (one
// or several, adjacent or not) or a from/to date range, and whether to compare with last
// year. Kept in the URL's query, so a view can be bookmarked and the back button works.

import type { Company, FinancialYear, Periods } from './api/types.ts'
import { updateQuery, useRoute } from './router.ts'

export interface Selection {
  companies: number[] // empty: all of them, combined
  fy: number | undefined
  months: string[] // "2026-04"
  from: string | undefined // "2026-04-01"
  to: string | undefined
  compare: boolean
}

export type Change = (change: Partial<Selection>) => void

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/
const MONTH = /^\d{4}-\d{2}$/

export function readSelection(query: URLSearchParams): Selection {
  const fy = query.get('fy')
  const from = query.get('from') ?? undefined
  const to = query.get('to') ?? undefined
  return {
    companies: query.getAll('company').filter((c) => /^\d+$/.test(c)).map(Number),
    fy: fy && /^\d{4}$/.test(fy) ? Number(fy) : undefined,
    months: query.getAll('month').filter((m) => MONTH.test(m)),
    from: from && ISO_DATE.test(from) ? from : undefined,
    to: to && ISO_DATE.test(to) ? to : undefined,
    compare: query.get('compare') !== '0', // compared with last year unless turned off
  }
}

/** The selection as URL query values (repeated keys for lists). */
export function selectionQuery(s: Selection): Record<string, string | string[] | undefined> {
  return {
    company: s.companies.map(String),
    fy: s.fy === undefined ? undefined : String(s.fy),
    month: s.months,
    from: s.from,
    to: s.to,
    compare: s.compare ? undefined : '0',
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
}

/** The period to show: the dates given, else the months asked for inside the year, else the
 *  year's months up to this month. */
export function chosenPeriod(selection: Selection, year: FinancialYear | undefined, today: string): PeriodChoice | undefined {
  if (selection.from && selection.to && selection.from <= selection.to) {
    return { months: [], from: selection.from, to: selection.to }
  }
  if (!year) return undefined
  const all = yearMonths(year)
  const asked = selection.months.filter((m) => all.includes(m))
  if (asked.length) return { months: asked }
  const upToNow = all.filter((m) => m <= today.slice(0, 7))
  return { months: upToNow.length ? upToNow : all }
}
