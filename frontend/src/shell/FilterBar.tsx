// The filter bar under the top bar (docs/design/dashboard.md Section 0.1, screen 5):
// - Companies: "All combined" or any combination of chips, each marked loaded or not loaded
//   in the source as a sync or entity-check last found it (the dashboard never asks);
// - Period: the financial year, month chips (one or several), or a from/to date range, and
//   compare with last year;
// - the status pill: how many selected companies were loaded, the last sync, the checks.

import { Input, Select, Tooltip } from 'antd'
import { useState } from 'react'
import type { Company, FinancialYear } from '../api/types.ts'
import { formatDate, formatMonth, parseDisplayDate, timeAgo } from '../format.ts'
import { periodDates, yearMonths, type Change, type PeriodChoice, type Selection } from '../selection.ts'

interface Props {
  companies: Company[]
  selection: Selection
  selectedIds: number[]
  years: FinancialYear[]
  year: FinancialYear | undefined
  period: PeriodChoice | undefined
  onChange: Change
}

function loadedText(c: Company): string {
  if (c.health.source_loaded === null || c.health.source_loaded === undefined) return 'not checked'
  return c.health.source_loaded ? 'loaded' : 'not loaded'
}

function CompanyChips({ companies, selection, onChange }: Pick<Props, 'companies' | 'selection' | 'onChange'>) {
  const all = selection.companies.length === 0
  const toggle = (id: number) => {
    const chosen = all ? [] : selection.companies
    const next = chosen.includes(id) ? chosen.filter((c) => c !== id) : [...chosen, id]
    onChange({ companies: next.length === companies.length ? [] : next })
  }
  const source = companies[0]?.health.source_name ?? 'the source'
  return (
    <div className="filter-row">
      <span className="filter-label">Companies</span>
      {companies.length > 1 && (
        <button type="button" className={all ? 'chip chip-all active' : 'chip chip-all'} aria-pressed={all} onClick={() => onChange({ companies: [] })}>
          All combined
        </button>
      )}
      {companies.map((c) => {
        const chosen = !all && selection.companies.includes(c.id)
        const checked = c.health.source_checked_at
        const state = loadedText(c)
        return (
          <Tooltip
            key={c.id}
            title={checked ? `${state} in ${source} when checked ${timeAgo(checked)} (${c.health.source_checked_by === 'entity_check' ? 'entity check' : 'sync'})` : `${source} not asked yet`}
          >
            <button type="button" className={chosen ? 'chip active' : 'chip'} aria-pressed={chosen} onClick={() => toggle(c.id)}>
              <span className={`dot dot-${state.replace(' ', '-')}`} aria-hidden />
              {c.name}
              <span className="chip-note">{state}</span>
            </button>
          </Tooltip>
        )
      })}
      <span className="filter-legend">
        <span className="dot dot-loaded" aria-hidden /> Loaded in {source} <span className="dot dot-not-loaded" aria-hidden /> Not loaded
        {companies.length > 1 ? ' (pick any combination)' : ''}
      </span>
    </div>
  )
}

function DateInput({ label, value, onDate }: { label: string; value: string | undefined; onDate: (iso: string) => void }) {
  const [text, setText] = useState<string | null>(null)
  const shown = text ?? (value ? formatDate(value) : '')
  const valid = text === null || text === '' || parseDisplayDate(text) !== null
  const commit = () => {
    if (text === null) return
    const iso = parseDisplayDate(text)
    if (iso) onDate(iso)
    if (iso || text === '') setText(null)
  }
  return (
    <Input
      aria-label={label}
      className="date-input"
      placeholder="DD-MMM-YYYY"
      value={shown}
      status={valid ? undefined : 'error'}
      onChange={(e) => setText(e.target.value)}
      onBlur={commit}
      onPressEnter={commit}
    />
  )
}

function PeriodRow({ selection, years, year, period, onChange }: Omit<Props, 'companies' | 'selectedIds'>) {
  const months = year ? yearMonths(year) : []
  const chosen = new Set(period?.months ?? [])
  const toggle = (m: string) => {
    const current = period?.months.length ? period.months : []
    const next = current.includes(m) ? current.filter((x) => x !== m) : [...current, m].sort()
    onChange({ months: next, from: undefined, to: undefined })
  }
  const [from, to] = period ? periodDates(period) : [undefined, undefined]
  return (
    <div className="filter-row">
      <span className="filter-label">Period</span>
      <Select
        aria-label="Financial year"
        value={year?.start_year}
        options={years.map((y) => ({ value: y.start_year, label: y.label }))}
        onChange={(fy: number) => onChange({ fy, months: [], from: undefined, to: undefined })}
        style={{ minWidth: 130 }}
      />
      {months.map((m) => (
        <button key={m} type="button" className={chosen.has(m) ? 'chip chip-month active' : 'chip chip-month'} aria-pressed={chosen.has(m)} onClick={() => toggle(m)}>
          {formatMonth(`${m}-01`).slice(0, 3)}
        </button>
      ))}
      <span className="filter-or">or dates</span>
      <DateInput label="From" value={from} onDate={(day) => onChange({ from: day, to, months: [] })} />
      <DateInput label="To" value={to} onDate={(day) => onChange({ to: day, from, months: [] })} />
      <Select
        aria-label="Compare"
        value={selection.compare ? 'last_year' : 'none'}
        options={[
          { value: 'last_year', label: 'Compare: last year' },
          { value: 'none', label: 'No comparison' },
        ]}
        onChange={(v: string) => onChange({ compare: v === 'last_year' })}
        style={{ minWidth: 170 }}
      />
    </div>
  )
}

export function StatusPill({ companies }: { companies: Company[] }) {
  if (!companies.length) return null
  const source = companies[0].health.source_name ?? 'Source'
  const loaded = companies.filter((c) => c.health.source_loaded).length
  const synced = companies.map((c) => c.health.last_sync_at).filter((d): d is string => !!d).sort().pop()
  const statuses = companies.map((c) => c.health.validation_status)
  const passed = statuses.every((s) => s === 'passed')
  const checks = passed ? 'all checks passed' : statuses.some((s) => s === 'failed') ? 'checks failed' : 'not all checked'
  return (
    <span className={passed && loaded === companies.length ? 'status-pill' : 'status-pill status-watch'}>
      {source}: {loaded} loaded · {synced ? `synced ${timeAgo(synced)}` : 'never synced'} · {checks}
    </span>
  )
}

export function FilterBar(props: Props) {
  const selected = props.companies.filter((c) => props.selectedIds.includes(c.id))
  return (
    <div className="filter-bar">
      <CompanyChips companies={props.companies} selection={props.selection} onChange={props.onChange} />
      <PeriodRow selection={props.selection} years={props.years} year={props.year} period={props.period} onChange={props.onChange} />
      <div className="filter-status">
        <StatusPill companies={selected} />
      </div>
    </div>
  )
}
