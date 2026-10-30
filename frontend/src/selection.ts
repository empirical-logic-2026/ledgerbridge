// What the user is looking at: the company (or all, combined), the financial year and the
// "as at" date. Kept in the URL's query, so a view can be bookmarked and the browser's
// back button works; the defaults (latest year, latest stored date) fill what's missing.

import type { Company, FinancialYear, Periods } from './api/types.ts'
import { navigate, useRoute } from './router.ts'

export const ALL = 'all'

export interface Selection {
  company: number | typeof ALL
  fy: number | undefined
  asOf: string | undefined
}

export function useSelection(): [Selection, (change: Partial<Selection>) => void] {
  const route = useRoute()
  const company = route.query.get('company')
  const fy = route.query.get('fy')
  const selection: Selection = {
    company: company && /^\d+$/.test(company) ? Number(company) : ALL,
    fy: fy && /^\d{4}$/.test(fy) ? Number(fy) : undefined,
    asOf: route.query.get('as_of') ?? undefined,
  }
  const change = (next: Partial<Selection>) => {
    const merged = { ...selection, ...next }
    navigate(route.path, {
      company: merged.company === ALL ? undefined : merged.company,
      fy: merged.fy,
      as_of: merged.asOf,
    })
  }
  return [selection, change]
}

/** The company ids the selection covers (every visible company for "all"). */
export function selectedIds(selection: Selection, companies: Company[] | undefined): number[] | undefined {
  if (!companies) return undefined
  if (selection.company === ALL) return companies.map((c) => c.id)
  return companies.some((c) => c.id === selection.company) ? [selection.company] : []
}

/** The year asked for, else the latest one. */
export function chosenYear(selection: Selection, periods: Periods | undefined): FinancialYear | undefined {
  const years = periods?.financial_years ?? []
  return years.find((y) => y.start_year === selection.fy) ?? years[0]
}

/** The "as at" dates stored inside the year, latest first. */
export function datesInYear(periods: Periods | undefined, year: FinancialYear | undefined): string[] {
  if (!periods || !year) return []
  return periods.as_at_dates.filter((d) => d >= year.start && d <= year.end)
}

/** The date asked for if it lies in the year, else the latest stored one, else the year's
 *  end or today, whichever is earlier. */
export function chosenDate(selection: Selection, periods: Periods | undefined, year: FinancialYear | undefined, today: string): string | undefined {
  if (!year) return undefined
  if (selection.asOf && selection.asOf >= year.start && selection.asOf <= year.end) return selection.asOf
  const stored = datesInYear(periods, year)
  if (stored.length) return stored[0]
  return year.end < today ? year.end : today
}
