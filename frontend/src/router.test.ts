import { describe, expect, it } from 'vitest'
import type { Company, FinancialYear } from './api/types.ts'
import { href, parseHash } from './router.ts'
import { chosenPeriod, readSelection, selectedIds, selectionQuery, yearMonths } from './selection.ts'

describe('the router', () => {
  it('reads the page and the query from the hash', () => {
    const route = parseHash('#/reports/dashboard?company=3&month=2026-04&month=2026-05')
    expect(route.path).toEqual(['reports', 'dashboard'])
    expect(route.query.getAll('month')).toEqual(['2026-04', '2026-05'])
    expect(parseHash('').path).toEqual([])
  })

  it('writes hrefs with repeated keys for lists and without empty values', () => {
    expect(href(['reports'], { company: [3, 4], fy: undefined, from: '' })).toBe('#/reports?company=3&company=4')
    expect(href([])).toBe('#/')
    expect(href(['a b'])).toBe('#/a%20b')
  })
})

const year: FinancialYear = { start_year: 2026, label: 'FY 2026-27', start: '2026-04-01', end: '2027-03-31' }
const health = {
  last_sync_at: null, validation_status: null, validated_as_of: null, validated_at: null,
  source_name: 'Tally', source_loaded: true, source_checked_at: null, source_checked_by: null,
}
const companies: Company[] = [3, 4, 5].map((id) => ({
  id, code: `C${id}`, name: `Company ${id}`, books_from: '2025-04-01', fy_start_month: 4, health,
}))

describe('the selection', () => {
  it('round-trips through the URL and ignores what it cannot read', () => {
    const read = readSelection(new URLSearchParams('company=3&company=x&fy=2026&month=2026-04&month=bad'))
    expect(read).toEqual({ companies: [3], fy: 2026, months: ['2026-04'], from: undefined, to: undefined, compare: true })
    expect(selectionQuery(read)).toEqual({ company: ['3'], fy: '2026', month: ['2026-04'], from: undefined, to: undefined, compare: undefined })
    // Compared with last year unless turned off.
    const off = readSelection(new URLSearchParams('compare=0'))
    expect(off.compare).toBe(false)
    expect(selectionQuery(off).compare).toBe('0')
  })

  it('covers every company when none is chosen, else any combination', () => {
    const none = readSelection(new URLSearchParams(''))
    expect(selectedIds(none, companies)).toEqual([3, 4, 5])
    expect(selectedIds({ ...none, companies: [5, 3] }, companies)).toEqual([3, 5])
    expect(selectedIds({ ...none, companies: [99] }, companies)).toEqual([3, 4, 5]) // not visible
  })

  it('lists the financial year month by month', () => {
    expect(yearMonths(year)).toEqual([
      '2026-04', '2026-05', '2026-06', '2026-07', '2026-08', '2026-09',
      '2026-10', '2026-11', '2026-12', '2027-01', '2027-02', '2027-03',
    ])
  })

  it('takes the dates given, else the months asked for, else the year up to this month', () => {
    const none = readSelection(new URLSearchParams(''))
    expect(chosenPeriod({ ...none, from: '2026-04-01', to: '2026-06-15' }, year, '2026-10-30')).toEqual({
      months: [], from: '2026-04-01', to: '2026-06-15',
    })
    expect(chosenPeriod({ ...none, months: ['2026-06', '2026-04', '2025-01'] }, year, '2026-10-30')).toEqual({
      months: ['2026-06', '2026-04'],
    })
    expect(chosenPeriod(none, year, '2026-10-30')?.months).toEqual([
      '2026-04', '2026-05', '2026-06', '2026-07', '2026-08', '2026-09', '2026-10',
    ])
    expect(chosenPeriod(none, year, '2028-01-01')?.months).toHaveLength(12) // a year gone by
    expect(chosenPeriod({ ...none, from: '2026-06-01', to: '2026-04-01' }, year, '2026-10-30')?.months).toHaveLength(7)
  })
})
