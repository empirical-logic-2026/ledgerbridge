// A key-figure card (docs/design/dashboard.md Section 0.3, screens 7 and 8): the label, the
// figure (short, the exact amount on hover; or a count, days, or a percentage), the change
// against the comparison period when compared ("vs previous period", "vs last year"; in
// percentage points for a percentage: F-CMP-001, F-CMP-003), and a note; the
// label opens the page behind the figure when there is one. Green when the change is good for the business, crimson when
// sales fall, neutral when e.g. returns rise, so that red keeps its meaning.

import { Tooltip } from 'antd'
import { formatChange, formatCompact, formatExact, toScaled } from '../format.ts'

export type Tone = 'up-good' | 'up-neutral'

export interface CardFigure {
  value: string | null
  before?: string | null // the comparison period's
  change_pct?: string | null
}

interface Props {
  label: string
  figure: CardFigure
  unit?: 'amount' | 'count' | 'days' | 'percent'
  tone?: Tone
  against?: string // what it is compared with ("previous period"); none: not compared
  note?: string
  alert?: boolean // crimson figure (e.g. overdue)
  missing?: string // why there is no figure
  to?: string // the page behind the figure
}

function shown(value: string, unit: Props['unit']): string {
  if (unit === 'count') return Number(value).toLocaleString('en-IN')
  if (unit === 'days') return `${Number(value).toLocaleString('en-IN')} days`
  if (unit === 'percent') return `${value}%`
  return formatCompact(value)
}

function capitalised(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1)
}

function changeText(change: string, unit: Props['unit']): string {
  const text = formatChange(change)
  return unit === 'percent' ? text.replace(/%$/, ' pts') : text
}

export function KeyCard({ label, figure, unit = 'amount', tone = 'up-good', against, note, alert, missing, to }: Props) {
  const value = figure.value
  const change = figure.change_pct
  let changeNode: React.ReactNode = null
  if (change) {
    const up = toScaled(change) >= 0n
    const css = tone === 'up-good' ? (up ? 'change good' : 'change bad') : up ? 'change neutral' : 'change good'
    const last = figure.before ? `${capitalised(against ?? 'before')}: ${unit === 'amount' ? formatExact(figure.before) : shown(figure.before, unit)}` : undefined
    changeNode = (
      <Tooltip title={last}>
        <span className={css}>{changeText(change, unit)} vs {against ?? 'before'}</span>
      </Tooltip>
    )
  } else if (against) {
    changeNode = <span className="card-small-note">Nothing to compare with in the {against}</span>
  }
  const text = value === null ? '—' : shown(value, unit)
  return (
    <section className="card card-small" aria-label={label}>
      {to ? (
        <a href={to} className="card-small-label card-row-link">
          {label}
        </a>
      ) : (
        <span className="card-small-label">{label}</span>
      )}
      <span className={alert && value !== null && toScaled(value) > 0n ? 'card-small-value negative' : 'card-small-value'}>
        {value === null ? (
          <Tooltip title={missing}>{text}</Tooltip>
        ) : unit === 'amount' ? (
          <Tooltip title={formatExact(value)}>{text}</Tooltip>
        ) : (
          text
        )}
      </span>
      {changeNode}
      {note && <span className="card-small-note">{note}</span>}
    </section>
  )
}
