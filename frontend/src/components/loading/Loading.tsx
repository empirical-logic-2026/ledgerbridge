// Pulse loading (docs/design/dashboard.md Section 0.5): while a page's data loads, each shared
// component shows a placeholder of its own shape (a key card, table rows, a chart area, ratio
// tiles), so the layout appears at once and nothing jumps when the data arrives. The rules:
// - the placeholders are laid out at once but shown only after SHOW_AFTER_MS (delay.ts), so
//   a quick load doesn't flicker;
// - the pulse is a CSS animation in the theme's colours (index.css, "pulse loading"), and
//   "prefers-reduced-motion: reduce" turns it into a static placeholder;
// - the loading area carries aria-busy and a screen-reader "Loading…".

import type { CSSProperties, ReactNode } from 'react'
import { useShownAfter } from './delay.ts'

/** One pulsing block: a line of text, a figure, a bar or a chart area. */
export function Pulse({ width = '100%', height = 12, style }: { width?: number | string; height?: number | string; style?: CSSProperties }) {
  return <span className="pulse" style={{ width, height, ...style }} />
}

/** A key card's shape: the label, the figure, the change and the sparkline. */
export function KpiSkeleton() {
  return (
    <div className="card card-small kpi-card skeleton-card">
      <Pulse width="45%" height={10} />
      <Pulse width="70%" height={26} />
      <Pulse width="55%" height={10} />
      <Pulse height={36} />
    </div>
  )
}

/** A row of key cards (the pages' "sales-cards" or the Overview's "home-kpis" grid). */
export function KpiRowSkeleton({ count, className = 'sales-cards' }: { count: number; className?: string }) {
  return (
    <div className={className}>
      {Array.from({ length: count }, (_, i) => (
        <KpiSkeleton key={i} />
      ))}
    </div>
  )
}

/** A chart's shape: the title and the drawing area. */
export function ChartSkeleton({ height = 260 }: { height?: number }) {
  return (
    <div className="card skeleton-card">
      <Pulse width="35%" height={14} />
      <Pulse height={height} style={{ marginTop: 12 }} />
    </div>
  )
}

/** A table's shape: the title, the header and the rows; the first column wider, as names are. */
export function TableSkeleton({ rows = 8, columns = 4 }: { rows?: number; columns?: number }) {
  const widths = (row: number) => Array.from({ length: columns }, (_, c) => (c === 0 ? `${55 + ((row * 7) % 30)}%` : `${50 + ((row + c) * 11) % 40}%`))
  return (
    <div className="card skeleton-card">
      <Pulse width="30%" height={14} />
      <div className="skeleton-table" style={{ gridTemplateColumns: `2fr repeat(${columns - 1}, 1fr)` }}>
        {Array.from({ length: columns }, (_, c) => (
          <Pulse key={`h${c}`} width="60%" height={10} />
        ))}
        {Array.from({ length: rows }, (_, r) => widths(r).map((w, c) => <Pulse key={`${r}-${c}`} width={w} height={12} />))}
      </div>
    </div>
  )
}

/** Ratio tiles' shape: a 2x2 grid of a label and a value. */
export function TilesSkeleton({ count = 4 }: { count?: number }) {
  return (
    <div className="card skeleton-card">
      <Pulse width="40%" height={14} />
      <div className="ratio-tiles" style={{ marginTop: 12 }}>
        {Array.from({ length: count }, (_, i) => (
          <div key={i} className="ratio-tile">
            <Pulse width="60%" height={10} />
            <Pulse width="40%" height={22} />
          </div>
        ))}
      </div>
    </div>
  )
}

/** The pages' shapes, from the components above:
 *  - overview: five key cards, the monthly chart beside the donut, two tables;
 *  - dashboard: four key cards, a chart, a table (Sales, Purchases, Stock, Cash Flow, Ageing);
 *  - statement: a statement table beside the ratio tiles (Balance Sheet);
 *  - kpis-report: two tile cards above a statement table (P&L & KPIs);
 *  - chart-report: a chart above a table (Monthly, Channels);
 *  - report: a long table (registers, lists, transactions). */
export type PageShape = 'overview' | 'dashboard' | 'statement' | 'kpis-report' | 'chart-report' | 'report'

function Shape({ shape }: { shape: PageShape }) {
  switch (shape) {
    case 'overview':
      return (
        <>
          <KpiRowSkeleton count={5} className="home-kpis" />
          <div className="home-charts">
            <ChartSkeleton height={300} />
            <ChartSkeleton height={300} />
          </div>
          <div className="home-tables">
            <TableSkeleton rows={6} />
            <TableSkeleton rows={6} columns={5} />
          </div>
        </>
      )
    case 'dashboard':
      return (
        <>
          <KpiRowSkeleton count={4} />
          <ChartSkeleton />
          <div className="skeleton-gap" />
          <TableSkeleton rows={6} columns={5} />
        </>
      )
    case 'statement':
      return (
        <div className="sheet-layout">
          <TableSkeleton rows={14} columns={4} />
          <div className="sheet-ratios">
            <TilesSkeleton />
            <TilesSkeleton />
          </div>
        </div>
      )
    case 'kpis-report':
      return (
        <>
          <div className="pnl-kpis">
            <TilesSkeleton />
            <TilesSkeleton />
          </div>
          <TableSkeleton rows={12} columns={4} />
        </>
      )
    case 'chart-report':
      return (
        <>
          <ChartSkeleton />
          <div className="skeleton-gap" />
          <TableSkeleton rows={10} columns={5} />
        </>
      )
    case 'report':
      return <TableSkeleton rows={12} columns={6} />
  }
}

/** The loading area: aria-busy, a screen-reader "Loading…", and the page's shape, which shows
 *  (pulsing) only after SHOW_AFTER_MS (delay.ts). */
export function Loading({ shape, label = 'Loading…', children }: { shape?: PageShape; label?: string; children?: ReactNode }) {
  const shown = useShownAfter()
  return (
    <div className="loading" aria-busy="true" data-testid="loading">
      <span className="sr-only" aria-live="polite">
        {label}
      </span>
      <div className={shown ? 'loading-shapes shown' : 'loading-shapes'} aria-hidden="true">
        {shape ? <Shape shape={shape} /> : children}
      </div>
    </div>
  )
}
