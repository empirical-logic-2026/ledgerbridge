// The table explorer on every table (docs/design/dashboard.md Section 0.3): which columns are
// shown, a filter (any part of a text cell, any case), sorting, grouping by a column with
// subtotals, the total, and the CSV of exactly what is shown. Pure functions on rows the page
// already has: tested in explorer.test.ts. Amounts are decimal strings added up as BigInt.

import type { ReactNode } from 'react'
import { formatDate, toScaled } from '../format.ts'
import { csvCell, exactRupees } from './reportTable.ts'

export type Kind = 'text' | 'date' | 'amount' | 'count'
export type Cell = string | number | null

export interface ExplorerColumn<R> {
  key: string
  label: string
  kind: Kind
  value: (row: R) => Cell // amount: a decimal string; count: a number; text and date: text
  link?: (row: R) => string | undefined // where the cell opens
  help?: string // what the column means, on hover; default: its label's in help/glossary.ts
  groupable?: boolean
  hidden?: boolean // not shown until chosen in Columns
  render?: (row: R) => ReactNode // shown instead of the value (e.g. a status tag); the value still sorts, filters and exports
  wrap?: boolean // long text (e.g. a status's meaning) wraps onto more lines
  summed?: boolean // false: no subtotal or total (e.g. a closing balance); amounts and counts are summed
}

export interface ExplorerState {
  columns: string[] // the keys shown, in the table's order
  groupBy: string | undefined
  filter: string
  sortKey: string | undefined
  descending: boolean
}

export interface Group<R> {
  key: string // the group's value as text ("" when empty)
  rows: R[]
  totals: Record<string, Cell>
}

export function defaultState<R>(columns: ExplorerColumn<R>[], sortKey?: string, descending = false): ExplorerState {
  return { columns: columns.filter((c) => !c.hidden).map((c) => c.key), groupBy: undefined, filter: '', sortKey, descending }
}

export function shownColumns<R>(columns: ExplorerColumn<R>[], state: ExplorerState): ExplorerColumn<R>[] {
  return columns.filter((c) => state.columns.includes(c.key))
}

/** The rows with any text or date cell containing the filter (any case). */
export function filterRows<R>(rows: R[], columns: ExplorerColumn<R>[], filter: string): R[] {
  const wanted = filter.trim().toLowerCase()
  if (!wanted) return rows
  const texts = columns.filter((c) => c.kind === 'text' || c.kind === 'date')
  const shown = (c: ExplorerColumn<R>, row: R) => {
    const value = c.value(row)
    return value === null ? '' : c.kind === 'date' ? `${value} ${formatDate(String(value))}` : String(value)
  }
  return rows.filter((row) => texts.some((c) => shown(c, row).toLowerCase().includes(wanted)))
}

function compare(a: Cell, b: Cell, kind: Kind): number {
  if (a === null || b === null) return a === b ? 0 : a === null ? 1 : -1
  if (kind === 'amount') {
    const x = toScaled(String(a))
    const y = toScaled(String(b))
    return x < y ? -1 : x > y ? 1 : 0
  }
  if (kind === 'count') return Number(a) - Number(b)
  return String(a).localeCompare(String(b))
}

export function sortRows<R>(rows: R[], columns: ExplorerColumn<R>[], state: ExplorerState): R[] {
  const column = columns.find((c) => c.key === state.sortKey)
  if (!column) return rows
  const sign = state.descending ? -1 : 1
  return [...rows].sort((a, b) => sign * compare(column.value(a), column.value(b), column.kind))
}

/** "12345000" (1/10,000 units) -> "1234.5000". */
export function fromScaled(value: bigint): string {
  const negative = value < 0n
  const text = (negative ? -value : value).toString().padStart(5, '0')
  return `${negative ? '-' : ''}${text.slice(0, -4)}.${text.slice(-4)}`
}

/** The sums of the amount and count columns (F-TBL-001). */
export function totals<R>(rows: R[], columns: ExplorerColumn<R>[]): Record<string, Cell> {
  const found: Record<string, Cell> = {}
  for (const c of columns) {
    if (c.summed === false) continue
    if (c.kind === 'amount') {
      found[c.key] = fromScaled(rows.reduce((sum, row) => sum + toScaled(String(c.value(row) ?? '0')), 0n))
    } else if (c.kind === 'count') {
      found[c.key] = rows.reduce((sum, row) => sum + Number(c.value(row) ?? 0), 0)
    }
  }
  return found
}

/** The rows grouped by a column's value, in the order the groups first appear, each with its
 *  subtotals (F-TBL-002). */
export function groupRows<R>(rows: R[], columns: ExplorerColumn<R>[], groupBy: string): Group<R>[] {
  const column = columns.find((c) => c.key === groupBy)
  if (!column) return []
  const groups = new Map<string, R[]>()
  for (const row of rows) {
    const key = String(column.value(row) ?? '')
    groups.set(key, [...(groups.get(key) ?? []), row])
  }
  return [...groups].map(([key, members]) => ({ key, rows: members, totals: totals(members, columns) }))
}

/** What the table shows, as CSV: the shown columns, exact amounts in rupees (two decimals),
 *  a subtotal after each group, and the total; text guarded against formulas. */
export function explorerCsv<R>(rows: R[], columns: ExplorerColumn<R>[], state: ExplorerState): string {
  const shown = shownColumns(columns, state)
  const cell = (c: ExplorerColumn<R>, value: Cell) => (value === null ? '' : c.kind === 'amount' ? exactRupees(String(value)) : String(value))
  const header = shown.map((c) => (c.kind === 'amount' ? `${c.label} (₹)` : c.label))
  const sumRow = (label: string, sums: Record<string, Cell>) =>
    shown.map((c, i) => (i === 0 ? label : c.key in sums ? cell(c, sums[c.key]) : ''))
  const body: string[][] = []
  const visible = sortRows(filterRows(rows, columns, state.filter), columns, state)
  if (state.groupBy) {
    for (const g of groupRows(visible, columns, state.groupBy)) {
      body.push(...g.rows.map((row) => shown.map((c) => cell(c, c.value(row)))))
      body.push(sumRow(`Subtotal: ${g.key || '(none)'}`, g.totals))
    }
  } else {
    body.push(...visible.map((row) => shown.map((c) => cell(c, c.value(row)))))
  }
  body.push(sumRow('Total', totals(visible, columns)))
  return [header, ...body].map((row) => row.map(csvCell).join(',')).join('\r\n') + '\r\n'
}

/** The state as a saved view's text, and back (unknown columns dropped). */
export function stateToText(state: ExplorerState): string {
  const q = new URLSearchParams()
  state.columns.forEach((c) => q.append('col', c))
  if (state.groupBy) q.set('group', state.groupBy)
  if (state.filter) q.set('filter', state.filter)
  if (state.sortKey) q.set('sort', `${state.descending ? '-' : ''}${state.sortKey}`)
  return q.toString()
}

export function stateFromText<R>(text: string, columns: ExplorerColumn<R>[]): ExplorerState {
  const q = new URLSearchParams(text)
  const keys = new Set(columns.map((c) => c.key))
  const sort = q.get('sort') ?? ''
  const sortKey = sort.replace(/^-/, '')
  const group = q.get('group') ?? undefined
  return {
    columns: q.getAll('col').filter((c) => keys.has(c)),
    groupBy: group && keys.has(group) ? group : undefined,
    filter: q.get('filter') ?? '',
    sortKey: keys.has(sortKey) ? sortKey : undefined,
    descending: sort.startsWith('-'),
  }
}
