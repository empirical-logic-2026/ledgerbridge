// Ratio tiles, two by two (docs/design/dashboard.md Section 0.4): each with its label, the
// figure (a percentage, a ratio or days), the change against the comparison in points when
// compared, and a note. Green when the change is good for the business, crimson when bad.

import { Tooltip } from 'antd'
import { formatChange, toScaled } from '../format.ts'

export interface Tile {
  label: string
  value: string | null
  unit: 'percent' | 'times' | 'days'
  change?: string | null // in points (percent), or the same unit
  higherIsBetter: boolean
  note?: string
  missing?: string // why there is no figure
}

function shown(tile: Tile): string {
  if (tile.value === null) return '—'
  if (tile.unit === 'percent') return `${tile.value}%`
  if (tile.unit === 'times') return `${tile.value}×`
  return `${Number(tile.value).toLocaleString('en-IN')} days`
}

function changeText(tile: Tile, change: string): string {
  const text = formatChange(change).replace(/%$/, '')
  return tile.unit === 'percent' ? `${text} pts` : tile.unit === 'days' ? `${text} days` : `${text}×`
}

export function RatioTiles({ label, tiles, against }: { label: string; tiles: Tile[]; against?: string }) {
  return (
    <div className="ratio-tiles" role="list" aria-label={label}>
      {tiles.map((t) => {
        const up = t.change ? toScaled(t.change) >= 0n : false
        const tone = t.change ? (up === t.higherIsBetter ? 'good' : 'bad') : undefined
        return (
          <div key={t.label} className="ratio-tile" role="listitem" aria-label={t.label}>
            <span className="ratio-label">{t.label}</span>
            <Tooltip title={t.value === null ? t.missing : undefined}>
              <span className="ratio-value">{shown(t)}</span>
            </Tooltip>
            {t.change && against && <span className={`change ${tone}`}>{changeText(t, t.change)} vs {against}</span>}
            {t.note && <span className="card-small-note">{t.note}</span>}
          </div>
        )
      })}
    </div>
  )
}
