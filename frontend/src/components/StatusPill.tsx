// A status pill in detail tables (docs/design/dashboard.md Section 0.4): green for good
// (current, paid, on track), crimson for bad (overdue, failed), grey for the rest. On hover, how
// the status is worked out (help/glossary.ts).

import { Explained } from './Explained.tsx'

export type PillTone = 'good' | 'bad' | 'neutral'

export function StatusPill({ text, tone, help }: { text: string; tone: PillTone; help?: string }) {
  return (
    <Explained label={text} help={help}>
      <span className={`status-pill status-${tone}`}>{text}</span>
    </Explained>
  )
}
