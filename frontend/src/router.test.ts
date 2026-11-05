import { describe, expect, it } from 'vitest'
import type { Company, FinancialYear } from './api/types.ts'
import { href, parseHash } from './router.ts'
import { chosenPeriod, comparisonQuery, quarterStart, readSelection, selectedIds, selectionQuery, yearMonths } from './selection.ts'

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
  id, code: `C${id}`, name: `Company ${id}`, display_name: `Company ${id}`, books_from: '2025-04-01', fy_start_month: 4, health,
}))

describe('the selection', () => {
  it('round-trips through the URL and ignores what it cannot read', () => {
    const read = readSelection(new URLSearchParams('company=3&company=x&fy=2026&month=2026-04&month=bad'))
    // Months given and no toggle (a link made before the toggles): Custom.
    expect(read).toEqual({ companies: [3], fy: 2026, toggle: 'custom', months: ['2026-04'], from: undefined, to: undefined, compare: 'previous', facets: { customer: [], channel: [], ledger_group: [], voucher_type: [] } })
    expect(selectionQuery(read)).toEqual({ company: ['3'], fy: '2026', p: 'custom', month: ['2026-04'], from: undefined, to: undefined, compare: undefined, customer: [], channel: [], group: [], vtype: [] })
    // Compared with the previous period unless asked otherwise; older links' "0" is off.
    expect(readSelection(new URLSearchParams('')).compare).toBe('previous')
    const off = readSelection(new URLSearchParams('compare=0'))
    expect(off.compare).toBe('none')
    expect(selectionQuery(off).compare).toBe('none')
    expect(readSelection(new URLSearchParams('compare=last_year')).compare).toBe('last_year')
    // The year to date by default; a toggle's months and dates aren't kept.
    const plain = readSelection(new URLSearchParams(''))
    expect(plain.toggle).toBe('ytd')
    expect(selectionQuery(plain).p).toBeUndefined()
    const mtd = readSelection(new URLSearchParams('p=mtd&month=2026-04'))
    expect(mtd.toggle).toBe('mtd')
    expect(selectionQuery(mtd).month).toEqual([])
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

  it('runs MTD, QTD and YTD to today, FY over the year chosen (RPT-016)', () => {
    const none = readSelection(new URLSearchParams(''))
    const years = [year]
    expect(chosenPeriod({ ...none, toggle: 'mtd' }, year, '2026-11-02', years)).toEqual({ months: [], from: '2026-11-01', to: '2026-11-02', span: 'month' })
    expect(chosenPeriod({ ...none, toggle: 'qtd' }, year, '2026-11-02', years)).toEqual({ months: [], from: '2026-10-01', to: '2026-11-02', span: 'quarter' })
    expect(chosenPeriod({ ...none, toggle: 'qtd' }, year, '2027-03-31', years)?.from).toBe('2027-01-01') // the year's fourth quarter
    expect(chosenPeriod({ ...none, toggle: 'ytd' }, year, '2026-11-02', years)).toEqual({ months: [], from: '2026-04-01', to: '2026-11-02', span: 'year' })
    expect(chosenPeriod({ ...none, toggle: 'fy' }, year, '2026-11-02', years)).toEqual({ months: yearMonths(year), span: 'year' })
    expect(quarterStart(year, '2026-06-30')).toBe('2026-04-01')
  })

  it('sends the span with the previous period only', () => {
    expect(comparisonQuery('previous', { months: [], from: '2026-11-01', to: '2026-11-02', span: 'month' })).toEqual({ compare: 'previous', span: 'month' })
    expect(comparisonQuery('last_year', { months: [], span: 'month' })).toEqual({ compare: 'last_year' })
    expect(comparisonQuery('previous', { months: ['2026-05'] })).toEqual({ compare: 'previous', span: undefined })
  })

  it('takes the dates given, else the months asked for, else the year up to this month (Custom)', () => {
    const none = { ...readSelection(new URLSearchParams('')), toggle: 'custom' as const }
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
