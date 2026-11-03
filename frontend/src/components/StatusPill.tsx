// A status pill in detail tables (docs/design/dashboard.md Section 0.4): green for good
// (current, paid, on track), crimson for bad (overdue, failed), grey for the rest.

export type PillTone = 'good' | 'bad' | 'neutral'

export function StatusPill({ text, tone }: { text: string; tone: PillTone }) {
  return <span className={`status-pill status-${tone}`}>{text}</span>
}
