import { describe, expect, it } from 'vitest'
import {
  formatCompact,
  formatDate,
  formatExact,
  formatMonth,
  indianGrouping,
  timeAgo,
  toLakhs,
  toScaled,
} from './format.ts'

describe('amounts', () => {
  it('are read exactly, never as floating point', () => {
    expect(toScaled('0.1')).toBe(1000n)
    expect(toScaled('-1234.5')).toBe(-12345000n)
    expect(toScaled('99999999999999999.9999')).toBe(999999999999999999999n)
    expect(() => toScaled('1e5')).toThrow()
    expect(() => toScaled('abc')).toThrow()
  })

  it('use Indian grouping', () => {
    expect(indianGrouping('999')).toBe('999')
    expect(indianGrouping('1000')).toBe('1,000')
    expect(indianGrouping('100000')).toBe('1,00,000')
    expect(indianGrouping('1620000')).toBe('16,20,000')
    expect(indianGrouping('123456789')).toBe('12,34,56,789')
  })

  it('show the exact amount in rupees and paise', () => {
    expect(formatExact('1620000.0000')).toBe('₹16,20,000.00')
    expect(formatExact('-500.505')).toBe('-₹500.51')
    expect(formatExact('0.0049')).toBe('₹0.00')
    expect(formatExact('0.1')).toBe('₹0.10') // exact here, unlike in floating point
  })

  it('shorten to lakhs and crores', () => {
    expect(formatCompact('48200000')).toBe('₹4.82 Cr')
    expect(formatCompact('6240000')).toBe('₹62.4 L')
    expect(formatCompact('100000')).toBe('₹1.0 L')
    expect(formatCompact('99999.4')).toBe('₹99,999')
    expect(formatCompact('-6240000')).toBe('-₹62.4 L')
    expect(formatCompact('1234567890123.4567')).toBe('₹1,23,456.79 Cr')
    expect(formatCompact('0')).toBe('₹0')
  })

  it('become lakhs for charts only', () => {
    expect(toLakhs('6240000')).toBe(62.4)
    expect(toLakhs('-150000.0000')).toBe(-1.5)
  })
})

describe('dates', () => {
  it('are written DD-MMM-YYYY without time zones', () => {
    expect(formatDate('2026-09-30')).toBe('30-Sep-2026')
    expect(formatDate('2026-01-02T23:59:59')).toBe('02-Jan-2026')
    expect(formatMonth('2026-04-01')).toBe('Apr-2026')
  })

  it('say how long ago, from UTC', () => {
    const now = new Date('2026-10-30T12:00:00Z')
    expect(timeAgo('2026-10-30T11:59:40', now)).toBe('just now')
    expect(timeAgo('2026-10-30T11:55:00', now)).toBe('5 min ago')
    expect(timeAgo('2026-10-30T09:00:00', now)).toBe('3 h ago')
    expect(timeAgo('2026-10-27T12:00:00Z', now)).toBe('3 days ago')
  })
})

describe('typed dates and changes', () => {
  it('reads DD-MMM-YYYY and refuses dates that do not exist', async () => {
    const { parseDisplayDate } = await import('./format.ts')
    expect(parseDisplayDate('01-Apr-2026')).toBe('2026-04-01')
    expect(parseDisplayDate(' 1-apr-2026 ')).toBe('2026-04-01')
    expect(parseDisplayDate('29-Feb-2028')).toBe('2028-02-29')
    expect(parseDisplayDate('29-Feb-2026')).toBeNull()
    expect(parseDisplayDate('2026-04-01')).toBeNull()
    expect(parseDisplayDate('01-Abc-2026')).toBeNull()
  })

  it('show a change with its direction', async () => {
    const { formatChange } = await import('./format.ts')
    expect(formatChange('12.0')).toBe('▲ 12%')
    expect(formatChange('-3.5')).toBe('▼ 3.5%')
    expect(formatChange('0.0')).toBe('▲ 0%')
  })
})
