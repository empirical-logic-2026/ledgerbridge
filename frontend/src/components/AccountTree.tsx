// Groups, sub-groups and ledgers as a tree table (ADR-055): the Trial Balance page and the
// Balance Sheet's drill-down. A group with rows under it opens and closes (its button says
// which, for the keyboard and screen readers); a ledger opens its Ledger statement. The
// amounts are formatted by the caller (Money), so the table never changes one.

import type { ReactNode } from 'react'
import { openable, visibleRows, type TreeRow } from './accountTree.ts'


interface Props {
  label: string // the table's accessible name
  columns: { label: ReactNode; className?: string }[] // the label column first
  rows: TreeRow[]
  open: Set<string> // the groups shown open
  onToggle: (key: string) => void
  footer?: TreeRow[] // totals, always shown
}

export function AccountTree({ label, columns, rows, open, onToggle, footer = [] }: Props) {
  const parents = openable(rows)
  const line = (row: TreeRow, total = false) => {
    const isOpen = open.has(row.key)
    const name = row.to ? <a href={row.to}>{row.label}</a> : row.label
    return (
      <tr key={row.key} className={total ? 'line-total' : `tree-${row.kind}`} data-figure="line" data-formula={row.formula} data-depth={row.depth}>
        <th scope="row" style={{ paddingLeft: `${0.75 + row.depth * 1.25}rem` }}>
          {parents.has(row.key) ? (
            <button type="button" className="tree-toggle" aria-expanded={isOpen} aria-label={`${isOpen ? 'Close' : 'Open'} ${row.label}`} onClick={() => onToggle(row.key)}>
              <span aria-hidden="true">{isOpen ? '▾' : '▸'}</span> {row.label}
            </button>
          ) : (
            <span className="tree-leaf">{name}</span>
          )}
        </th>
        {row.cells.map((cell, n) => (
          <td key={n} className="num">
            {cell}
          </td>
        ))}
      </tr>
    )
  }
  return (
    <div className="report-table-wrap">
      <table className="report-table account-tree" aria-label={label}>
        <thead>
          <tr>
            {columns.map((c, n) => (
              <th key={n} className={n === 0 ? undefined : (c.className ?? 'num')}>
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>{visibleRows(rows, open).map((row) => line(row))}</tbody>
        {footer.length > 0 && <tfoot>{footer.map((row) => line(row, true))}</tfoot>}
      </table>
    </div>
  )
}
