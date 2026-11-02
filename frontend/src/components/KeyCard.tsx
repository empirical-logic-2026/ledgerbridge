// A key-figure card (docs/design/dashboard.md Section 0.3, screens 7 and 8): the label, the
// figure (short, the exact amount on hover; or a count, days, or a percentage), the change
// against the comparison period when compared ("vs previous period", "vs last year"; in
// percentage points for a percentage: F-CMP-001, F-CMP-003), and a note; the
// label opens the page behind the figure when there is one. In the reference pattern (Section 0.4):
// a coloured top border, a small-capitals label and a sparkline of the recent months. Green when
// the change is good for the business, crimson when sales fall, neutral when e.g. returns rise,
// so that red keeps its meaning.

import { Tooltip } from 'antd'
import type { EChartsOption } from 'echarts'
import { EChart } from './EChart.tsx'
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
  accent?: string // the top border's colour
  spark?: (number | null)[] // the recent months, oldest first (drawing only)
  sparkColour?: string
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

function sparkline(values: (number | null)[], colour: string): EChartsOption {
  return {
    backgroundColor: 'transparent',
    grid: { left: 2, right: 2, top: 4, bottom: 2 },
    xAxis: { type: 'category', show: false, data: values.map((_, i) => i) },
    yAxis: { type: 'value', show: false, scale: true },
    series: [{ type: 'line', data: values, symbol: 'none', smooth: true, lineStyle: { color: colour, width: 2 }, connectNulls: false }],
  }
}

export function KeyCard({ label, figure, unit = 'amount', tone = 'up-good', against, note, alert, missing, to, accent, spark, sparkColour }: Props) {
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
    <section className={accent ? 'card card-small kpi-card' : 'card card-small'} aria-label={label} style={accent ? { borderTopColor: accent } : undefined}>
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
      {spark && spark.some((v) => v !== null) && (
        <div className="kpi-spark" aria-hidden>
          <EChart option={sparkline(spark, sparkColour ?? accent ?? 'currentColor')} height={36} />
        </div>
      )}
    </section>
  )
}
