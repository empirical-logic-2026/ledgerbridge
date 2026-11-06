// Horizontal bars (docs/design/dashboard.md Section 0.4): one row per part with its label, a bar
// for its share, the share in percent and the short amount (exact on hover). Used for the ageing
// buckets and the cost structure (as % of net sales). The share comes from the caller, worked
// out from exact amounts.

import { Money } from './Money.tsx'

export interface Bar {
  label: string
  amount: string // exact decimal
  share: number | null // percent of the whole, for the bar's length and the figure shown
  colour: string
  to?: string // the page behind it
}

export function HBars({ label, bars }: { label: string; bars: Bar[] }) {
  return (
    <div className="hbars" role="list" aria-label={label}>
      {bars.map((b) => (
        <div key={b.label} className="hbar" role="listitem">
          <span className="hbar-label">{b.to ? <a href={b.to}>{b.label}</a> : b.label}</span>
          <span className="hbar-track">
            <span className="hbar-fill" style={{ width: `${Math.max(0, Math.min(100, b.share ?? 0))}%`, background: b.colour }} />
          </span>
          <span className="hbar-share">{b.share === null ? '—' : `${b.share.toFixed(1)}%`}</span>
          <Money value={b.amount} className="hbar-amount" />
        </div>
      ))}
    </div>
  )
}
