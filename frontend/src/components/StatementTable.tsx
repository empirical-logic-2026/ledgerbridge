// A statement table (docs/design/dashboard.md Section 0.4, the reference pattern's "FY2025 /
// FY2024 / % CHG"): each line with this period's figure, the comparison period's and the
// change; section headings ("Assets"), indented lines and bold totals; a line's label opens the
// page behind it. Used by the Overview's Profit & Loss summary and the Balance Sheet. The
// figures are formatted by the caller (Money, percentages), so the table never changes one.

import type { ReactNode } from 'react'
import { formatChange, toScaled } from '../format.ts'

export interface StatementRow {
  key: string
  label: ReactNode
  kind?: 'line' | 'total' // a total is bold
  level?: string // the indentation class: line-<level> (e.g. "sub", "detail")
  current: ReactNode
  previous?: ReactNode
  change?: ReactNode
  to?: string // the page behind the line
}

export interface StatementSection {
  key: string
  title?: string // a heading row ("Assets")
  rows: StatementRow[]
}

interface Props {
  label: string // the table's accessible name
  columns: { label: ReactNode; current: ReactNode; previous?: ReactNode; change?: ReactNode }
  sections: StatementSection[]
  compared: boolean // show the comparison period and the change
  compact?: boolean
}

function rowClass(row: StatementRow): string | undefined {
  const classes = [row.level ? `line-${row.level}` : '', row.kind === 'total' ? 'line-total' : ''].filter(Boolean)
  return classes.length ? classes.join(' ') : undefined
}

export function StatementTable({ label, columns, sections, compared, compact }: Props) {
  const width = compared ? 4 : 2
  return (
    <div className="report-table-wrap">
      <table className={compact ? 'report-table statement-table compact' : 'report-table statement-table'} aria-label={label}>
        <thead>
          <tr>
            <th>{columns.label}</th>
            <th className="num">{columns.current}</th>
            {compared && <th className="num">{columns.previous}</th>}
            {compared && <th className="num">{columns.change}</th>}
          </tr>
        </thead>
        {sections.map((section) => (
          <tbody key={section.key}>
            {section.title && (
              <tr className="line-section">
                <th scope="rowgroup" colSpan={width}>
                  {section.title}
                </th>
              </tr>
            )}
            {section.rows.map((row) => (
              <tr key={row.key} className={rowClass(row)}>
                <th scope="row">{row.to ? <a href={row.to}>{row.label}</a> : row.label}</th>
                <td className="num">{row.current}</td>
                {compared && <td className="num">{row.previous}</td>}
                {compared && <td className="num">{row.change ?? <span className="muted">—</span>}</td>}
              </tr>
            ))}
          </tbody>
        ))}
      </table>
    </div>
  )
}

/** A change: "▲ 12%" (or "▼ 1.1 pts" for a percentage), green when good for the business,
 *  crimson when bad, grey for a cost going up; "—" when there is none. Without
 *  `higherIsBetter` it is grey either way (e.g. a Balance Sheet line). */
export function StatementChange({ change, higherIsBetter, points }: { change: string | null | undefined; higherIsBetter?: boolean; points?: boolean }) {
  if (!change) return <span className="muted">—</span>
  const up = toScaled(change) >= 0n
  const tone = higherIsBetter === undefined ? 'neutral' : up === higherIsBetter ? 'good' : higherIsBetter ? 'bad' : 'neutral'
  const text = formatChange(change)
  return <span className={`change ${tone}`}>{points ? text.replace(/%$/, ' pts') : text}</span>
}
