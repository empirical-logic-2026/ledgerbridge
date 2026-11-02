import { describe, expect, it } from 'vitest'
import {
  defaultState,
  explorerCsv,
  filterRows,
  fromScaled,
  groupRows,
  sortRows,
  stateFromText,
  stateToText,
  totals,
  type ExplorerColumn,
} from './explorer.ts'

interface Row {
  date: string
  type: string
  party: string
  amount: string
  lines: number
}

const rows: Row[] = [
  { date: '2026-04-02', type: 'Sales', party: 'Alpha', amount: '100.5000', lines: 2 },
  { date: '2026-04-09', type: 'Credit Note', party: '=cmd', amount: '-20.2500', lines: 1 },
  { date: '2026-05-01', type: 'Sales', party: 'Beta', amount: '300', lines: 3 },
]
const columns: ExplorerColumn<Row>[] = [
  { key: 'date', label: 'Date', kind: 'date', value: (r) => r.date },
  { key: 'type', label: 'Vch Type', kind: 'text', value: (r) => r.type, groupable: true },
  { key: 'party', label: 'Party', kind: 'text', value: (r) => r.party },
  { key: 'amount', label: 'Amount', kind: 'amount', value: (r) => r.amount },
  { key: 'lines', label: 'Lines', kind: 'count', value: (r) => r.lines, hidden: true },
]

describe('the table explorer', () => {
  it('shows the columns not hidden', () => {
    expect(defaultState(columns).columns).toEqual(['date', 'type', 'party', 'amount'])
  })

  it('filters on text and on dates as shown', () => {
    expect(filterRows(rows, columns, 'BETA')).toHaveLength(1)
    expect(filterRows(rows, columns, 'apr-2026')).toHaveLength(2)
    expect(filterRows(rows, columns, '300')).toHaveLength(0) // amounts aren't text
  })

  it('sorts amounts exactly, either way', () => {
    const state = { ...defaultState(columns), sortKey: 'amount', descending: true }
    expect(sortRows(rows, columns, state).map((r) => r.party)).toEqual(['Beta', 'Alpha', '=cmd'])
  })

  it('adds up amounts without rounding, and counts', () => {
    expect(totals(rows, columns)).toEqual({ amount: '380.2500', lines: 6 })
    expect(fromScaled(-5n)).toBe('-0.0005')
    expect(totals(rows, [{ ...columns[3], summed: false }])).toEqual({})
  })

  it('groups with subtotals, in the order groups appear', () => {
    const groups = groupRows(rows, columns, 'type')
    expect(groups.map((g) => [g.key, g.rows.length, g.totals.amount])).toEqual([
      ['Sales', 2, '400.5000'],
      ['Credit Note', 1, '-20.2500'],
    ])
  })

  it('exports what is shown, grouped, with exact rupees and guarded text', () => {
    const state = { ...defaultState(columns), groupBy: 'type' }
    expect(explorerCsv(rows, columns, state).split('\r\n')).toEqual([
      'Date,Vch Type,Party,Amount (₹)',
      '2026-04-02,Sales,Alpha,100.50',
      '2026-05-01,Sales,Beta,300.00',
      'Subtotal: Sales,,,400.50',
      "2026-04-09,Credit Note,'=cmd,-20.25",
      'Subtotal: Credit Note,,,-20.25',
      'Total,,,380.25',
      '',
    ])
  })

  it('keeps a saved view as text and reads it back, dropping unknown columns', () => {
    const state = { ...defaultState(columns), groupBy: 'type', filter: 'sa', sortKey: 'amount', descending: true }
    expect(stateFromText(stateToText(state), columns)).toEqual(state)
    expect(stateFromText('col=nope&col=date&group=nope', columns)).toMatchObject({ columns: ['date'], groupBy: undefined })
  })
})
