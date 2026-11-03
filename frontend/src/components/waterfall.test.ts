import { describe, expect, it } from 'vitest'
import { waterfallBars } from './waterfall.ts'

describe('a waterfall', () => {
  it('floats each movement from the running total, between the opening and closing bars', () => {
    const bars = waterfallBars([
      { label: 'Opening', amount: '1000000' },
      { label: 'Customers', amount: '500000' },
      { label: 'Suppliers', amount: '-300000' },
      { label: 'Closing', amount: '1200000' },
    ])
    expect(bars.map((b) => [b.label, b.base, b.height, b.kind])).toEqual([
      ['Opening', 0, 10, 'total'],
      ['Customers', 10, 5, 'up'],
      ['Suppliers', 12, 3, 'down'],
      ['Closing', 0, 12, 'total'],
    ])
  })

  it('has no bars without an opening and a closing', () => {
    expect(waterfallBars([{ label: 'Opening', amount: '1' }])).toEqual([])
  })
})
