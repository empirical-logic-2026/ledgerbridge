import { describe, expect, it } from 'vitest'
import { shares } from './shares.ts'

describe("a mix's shares", () => {
  it('are each part of the positive total, one decimal', () => {
    expect(shares([{ name: 'A', amount: '300' }, { name: 'B', amount: '100' }])).toEqual([75, 25])
    expect(shares([{ name: 'A', amount: '2' }, { name: 'B', amount: '1' }])).toEqual([66.7, 33.3])
  })

  it('count a negative part as nothing, and have none without a total', () => {
    expect(shares([{ name: 'A', amount: '100' }, { name: 'B', amount: '-50' }])).toEqual([100, 0])
    expect(shares([{ name: 'A', amount: '0' }])).toEqual([0])
  })
})
