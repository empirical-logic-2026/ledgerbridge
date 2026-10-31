// The options side panel of every report page (docs/design/dashboard.md Section 0.1, screen 6),
// on charcoal: whether the figures match Tally for the selection, view as, columns, open
// related reports, saved views, export, and "What is this?". The page passes what each section
// holds; the panel only lays them out and handles saved views.

import { Button, Checkbox, Input, Radio } from 'antd'
import { useState, type ReactNode } from 'react'
import type { MatchingOut } from '../api/types.ts'
import { formatDate } from '../format.ts'
import { href, type Query } from '../router.ts'
import { deleteView, loadViews, saveView, type SavedView } from './savedViews.ts'

export interface Choice<T extends string> {
  key: T
  label: string
  disabled?: boolean
}

export interface Related {
  label: string
  path: string[]
}

interface Props<V extends string, C extends string> {
  title: string // "Profit & Loss options"
  page: string // where saved views are kept: "profit-loss"
  matching: MatchingOut | undefined
  companiesLabel: string // "both companies", "LedgerBridge Test Co"
  sourceName: string
  views: Choice<V>[]
  view: V
  onView: (view: V) => void
  extraViews?: ReactNode // e.g. "As % of sales"
  columns: Choice<C>[]
  shown: C[]
  onColumns: (columns: C[]) => void
  related: Related[]
  query: Query // kept on the related links
  currentQuery: string // saved with a view
  onApplyView: (query: string) => void
  onExport: () => void
  help: ReactNode
  onClose: () => void
}

export function MatchStatus({ matching, companiesLabel, sourceName }: { matching: MatchingOut | undefined; companiesLabel: string; sourceName: string }) {
  if (!matching) return null
  const last = matching.dates.length ? formatDate(matching.dates[matching.dates.length - 1]) : null
  if (matching.matches) {
    return (
      <p className="match match-ok" role="status">
        ✓ Matches {sourceName} for {companiesLabel}
        {last ? ` (checked at ${matching.dates.length} statement dates up to ${last})` : ''}
      </p>
    )
  }
  if (matching.differing > 0) {
    return (
      <p className="match match-bad" role="status">
        ✗ {matching.differing} line{matching.differing === 1 ? '' : 's'} differ from {sourceName} at the dates used. See Data checks, or run{' '}
        <code>./dev.ps1 statements</code>.
      </p>
    )
  }
  return (
    <p className="match match-unknown" role="status">
      Not yet compared with {sourceName} for {matching.unchecked} of the companies and dates used: run{' '}
      <code>./dev.ps1 statements</code>.
    </p>
  )
}

export function OptionsPanel<V extends string, C extends string>(props: Props<V, C>) {
  const [views, setViews] = useState<SavedView[]>(() => loadViews(props.page))
  const [name, setName] = useState('')
  const save = () => {
    const trimmed = name.trim()
    if (!trimmed) return
    setViews(saveView(props.page, { name: trimmed, query: props.currentQuery }))
    setName('')
  }
  return (
    <aside className="options-panel" aria-label={props.title}>
      <div className="options-head">
        <h2>{props.title}</h2>
        <Button type="text" className="on-dark" aria-label="Close the options" onClick={props.onClose}>
          ×
        </Button>
      </div>
      <MatchStatus matching={props.matching} companiesLabel={props.companiesLabel} sourceName={props.sourceName} />

      <section aria-label="View as">
        <h3>View as</h3>
        <Radio.Group value={props.view} onChange={(e) => props.onView(e.target.value)} className="options-list">
          {props.views.map((v) => (
            <Radio key={v.key} value={v.key} disabled={v.disabled}>
              {v.label}
            </Radio>
          ))}
        </Radio.Group>
        {props.extraViews}
      </section>

      <section aria-label="Columns">
        <h3>Columns</h3>
        <Checkbox.Group value={props.shown} onChange={(values) => props.onColumns(values as C[])} className="options-list">
          {props.columns.map((c) => (
            <Checkbox key={c.key} value={c.key} disabled={c.disabled}>
              {c.label}
            </Checkbox>
          ))}
        </Checkbox.Group>
      </section>

      {props.related.length > 0 && (
        <section aria-label="Open related">
          <h3>Open related</h3>
          {props.related.map((r) => (
            <a key={r.label} href={href(r.path, props.query)} className="options-link">
              {r.label} →
            </a>
          ))}
        </section>
      )}

      <section aria-label="Saved views">
        <h3>Saved views</h3>
        {views.length === 0 && <p className="options-muted">None saved yet (kept in this browser).</p>}
        {views.map((v) => (
          <div key={v.name} className="options-view">
            <Button type="link" className="options-link" onClick={() => props.onApplyView(v.query)}>
              {v.name}
            </Button>
            <Button type="text" className="on-dark" aria-label={`Delete saved view ${v.name}`} onClick={() => setViews(deleteView(props.page, v.name))}>
              ×
            </Button>
          </div>
        ))}
        <div className="options-save">
          <Input size="small" aria-label="Name of the view" placeholder="Name this view" value={name} onChange={(e) => setName(e.target.value)} onPressEnter={save} />
          <Button size="small" onClick={save}>
            + Save current view
          </Button>
        </div>
      </section>

      <section aria-label="Export">
        <h3>Export</h3>
        <div className="options-export">
          <Button type="primary" onClick={props.onExport}>
            CSV
          </Button>
          <Button disabled>Excel (later)</Button>
          <Button disabled>PDF (later)</Button>
        </div>
      </section>

      <section aria-label="What is this?" className="options-help">
        <h3>What is this?</h3>
        {props.help}
      </section>
    </aside>
  )
}
