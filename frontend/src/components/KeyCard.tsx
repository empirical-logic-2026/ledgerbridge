// A key-figure card (docs/design/dashboard.md Section 0.3, screens 7 and 8): the label, the
// figure (short, the exact amount on hover; or a count, or days), the change against last
// year when compared, and a note. Green when the change is good for the business, crimson when
// sales fall, neutral when e.g. returns rise, so that red keeps its meaning.

import { Tooltip } from 'antd'
import { formatChange, formatCompact, formatExact, toScaled } from '../format.ts'

export type Tone = 'up-good' | 'up-neutral'

export interface CardFigure {
  value: string | null
  last_year?: string | null
  change_pct?: string | null
}

interface Props {
  label: string
  figure: CardFigure
  unit?: 'amount' | 'count' | 'days'
  tone?: Tone
  compared?: boolean // last year was asked for
  note?: string
  alert?: boolean // crimson figure (e.g. overdue)
  missing?: string // why there is no figure
}

function shown(value: string, unit: Props['unit']): string {
  if (unit === 'count') return Number(value).toLocaleString('en-IN')
  if (unit === 'days') return `${Number(value).toLocaleString('en-IN')} days`
  return formatCompact(value)
}

export function KeyCard({ label, figure, unit = 'amount', tone = 'up-good', compared = false, note, alert, missing }: Props) {
  const value = figure.value
  const change = figure.change_pct
  let changeNode: React.ReactNode = null
  if (change) {
    const up = toScaled(change) >= 0n
    const css = tone === 'up-good' ? (up ? 'change good' : 'change bad') : up ? 'change neutral' : 'change good'
    const last = figure.last_year ? `Last year ${unit === 'amount' ? formatExact(figure.last_year) : shown(figure.last_year, unit)}` : undefined
    changeNode = (
      <Tooltip title={last}>
        <span className={css}>{formatChange(change)} vs last year</span>
      </Tooltip>
    )
  } else if (compared) {
    changeNode = <span className="card-small-note">Nothing last year to compare with</span>
  }
  const text = value === null ? '—' : shown(value, unit)
  return (
    <section className="card card-small" aria-label={label}>
      <span className="card-small-label">{label}</span>
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
