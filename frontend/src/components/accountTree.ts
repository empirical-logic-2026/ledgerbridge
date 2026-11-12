// The tree table's rows and which of them show (components/AccountTree.tsx; ADR-055).

import type { ReactNode } from 'react'

export interface TreeRow {
  key: string
  label: string
  kind: string // group, ledger, stock, line, difference
  depth: number
  parent: string | null
  cells: ReactNode[] // one per amount column
  to?: string // the page behind the row (a ledger's statement, the stock summary)
  formula: string // its formula ID (docs/formula-sheet.md)
}

/** The rows to show: a row whose parents are all open. */
export function visibleRows(rows: TreeRow[], open: Set<string>): TreeRow[] {
  const byKey = new Map(rows.map((r) => [r.key, r]))
  const shown = (row: TreeRow): boolean => {
    if (row.parent === null) return true
    const parent = byKey.get(row.parent)
    return parent === undefined ? true : open.has(parent.key) && shown(parent)
  }
  return rows.filter(shown)
}

/** The groups that have rows under them. */
export function openable(rows: TreeRow[]): Set<string> {
  return new Set(rows.flatMap((r) => (r.parent === null ? [] : [r.parent])))
}
