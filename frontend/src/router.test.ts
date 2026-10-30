import { describe, expect, it } from 'vitest'
import type { Periods } from './api/types.ts'
import { href, parseHash } from './router.ts'
import { chosenDate, chosenYear, datesInYear, type Selection } from './selection.ts'

describe('the router', () => {
  it('reads the page and the query from the hash', () => {
    const route = parseHash('#/overview/summary?company=3&fy=2026')
    expect(route.path).toEqual(['overview', 'summary'])
    expect(route.query.get('company')).toBe('3')
    expect(parseHash('').path).toEqual([])
  })

  it('writes hrefs without empty values', () => {
    expect(href(['overview'], { company: 3, fy: undefined, as_of: '' })).toBe('#/overview?company=3')
    expect(href([])).toBe('#/')
    expect(href(['a b'])).toBe('#/a%20b')
  })
})

const periods: Periods = {
  financial_years: [
    { start_year: 2026, label: 'FY 2026-27', start: '2026-04-01', end: '2027-03-31' },
    { start_year: 2025, label: 'FY 2025-26', start: '2025-04-01', end: '2026-03-31' },
  ],
  as_at_dates: ['2026-09-30', '2026-08-31', '2026-03-31'],
}
const none: Selection = { company: 'all', fy: undefined, asOf: undefined }

describe('the selection', () => {
  it('defaults to the latest year and its latest stored date', () => {
    const year = chosenYear(none, periods)
    expect(year?.start_year).toBe(2026)
    expect(datesInYear(periods, year)).toEqual(['2026-09-30', '2026-08-31'])
    expect(chosenDate(none, periods, year, '2026-10-30')).toBe('2026-09-30')
  })

  it('keeps a date asked for inside the year, and ignores one outside it', () => {
    const year = chosenYear({ ...none, fy: 2025 }, periods)
    expect(chosenDate({ ...none, fy: 2025, asOf: '2025-12-31' }, periods, year, '2026-10-30')).toBe(
      '2025-12-31',
    )
    expect(chosenDate({ ...none, fy: 2025, asOf: '2026-09-30' }, periods, year, '2026-10-30')).toBe(
      '2026-03-31',
    )
  })

  it('without stored dates uses the year end or today, whichever is earlier', () => {
    const bare: Periods = { ...periods, as_at_dates: [] }
    const year = chosenYear(none, bare)
    expect(chosenDate(none, bare, year, '2026-10-30')).toBe('2026-10-30')
  })
})
