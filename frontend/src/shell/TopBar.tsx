// The top filter bar (docs/design/dashboard.md Section 0.2, screen 7): the breadcrumbs, the
// period (financial year, months, from/to dates, compare), the companies (all combined or any
// combination, each marked loaded or not loaded in the source as last checked: the dashboard
// never asks), the facets (customer, channel, ledger group, voucher type: applied by the pages
// whose figures can be filtered by them, else disabled with the reason), and Copy link.

import { useQuery } from '@tanstack/react-query'
import { App as AntApp, Breadcrumb, Button, Input, Popover, Select, Tooltip } from 'antd'
import { useState } from 'react'
import { getJson } from '../api/client.ts'
import type { Company, FacetValue, FinancialYear } from '../api/types.ts'
import { formatDate, formatMonth, parseDisplayDate, timeAgo } from '../format.ts'
import { href, type Query } from '../router.ts'
import { periodDates, yearMonths, type Change, type PeriodChoice, type Selection } from '../selection.ts'
import type { Facet, NavPage } from './nav.ts'

export interface Crumb {
  label: string
  path?: string[] // omitted for the current page
}

interface Props {
  crumbs: Crumb[]
  page: NavPage | undefined
  companies: Company[]
  selection: Selection
  selectedIds: number[]
  years: FinancialYear[]
  year: FinancialYear | undefined
  period: PeriodChoice | undefined
  onChange: Change
  query: Query
}

const FACETS: { key: Facet; label: string }[] = [
  { key: 'customer', label: 'Customer' },
  { key: 'channel', label: 'Channel' },
  { key: 'ledger_group', label: 'Ledger group' },
  { key: 'voucher_type', label: 'Voucher type' },
]

function loadedText(c: Company): string {
  if (c.health.source_loaded === null || c.health.source_loaded === undefined) return 'not checked'
  return c.health.source_loaded ? 'loaded' : 'not loaded'
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
    <Input aria-label={label} className="date-input" placeholder="DD-MMM-YYYY" value={shown} status={valid ? undefined : 'error'}
      onChange={(e) => setText(e.target.value)} onBlur={commit} onPressEnter={commit} />
  )
}

function periodLabel(year: FinancialYear | undefined, period: PeriodChoice | undefined, compare: boolean): string {
  if (!period) return 'Period'
  const [from, to] = periodDates(period)
  let text: string
  if (period.months.length && year) {
    const sorted = [...period.months].sort()
    const first = formatMonth(`${sorted[0]}-01`).slice(0, 3)
    const last = formatMonth(`${sorted[sorted.length - 1]}-01`).slice(0, 3)
    text = `${year.label} · ${sorted.length === 1 ? first : `${first}–${last}`}${sorted.length > 1 && sorted.length !== monthsBetween(sorted) ? ' (some months)' : ''}`
  } else {
    text = `${formatDate(from)} to ${formatDate(to)}`
  }
  return compare ? `${text} · vs last year` : text
}

function monthsBetween(sorted: string[]): number {
  const [y1, m1] = sorted[0].split('-').map(Number)
  const [y2, m2] = sorted[sorted.length - 1].split('-').map(Number)
  return (y2 - y1) * 12 + (m2 - m1) + 1
}

function PeriodPicker({ selection, years, year, period, onChange }: Pick<Props, 'selection' | 'years' | 'year' | 'period' | 'onChange'>) {
  const months = year ? yearMonths(year) : []
  const chosen = new Set(period?.months ?? [])
  const [from, to] = period ? periodDates(period) : [undefined, undefined]
  const toggle = (m: string) => {
    const current = period?.months.length ? period.months : []
    const next = current.includes(m) ? current.filter((x) => x !== m) : [...current, m].sort()
    onChange({ months: next, from: undefined, to: undefined })
  }
  const panel = (
    <div className="picker-panel" aria-label="Period">
      <div className="picker-row">
        <span className="picker-label">Year</span>
        <Select aria-label="Financial year" value={year?.start_year} options={years.map((y) => ({ value: y.start_year, label: y.label }))}
          onChange={(fy: number) => onChange({ fy, months: [], from: undefined, to: undefined })} style={{ minWidth: 130 }} />
      </div>
      <div className="picker-row picker-months">
        {months.map((m) => (
          <button key={m} type="button" className={chosen.has(m) ? 'chip chip-month active' : 'chip chip-month'} aria-pressed={chosen.has(m)} onClick={() => toggle(m)}>
            {formatMonth(`${m}-01`).slice(0, 3)}
          </button>
        ))}
      </div>
      <div className="picker-row">
        <span className="picker-label">Or dates</span>
        <DateInput label="From" value={from} onDate={(day) => onChange({ from: day, to, months: [] })} />
        <DateInput label="To" value={to} onDate={(day) => onChange({ to: day, from, months: [] })} />
      </div>
      <div className="picker-row">
        <span className="picker-label">Compare</span>
        <Select aria-label="Compare" value={selection.compare ? 'last_year' : 'none'}
          options={[{ value: 'last_year', label: 'With last year' }, { value: 'none', label: 'No comparison' }]}
          onChange={(v: string) => onChange({ compare: v === 'last_year' })} style={{ minWidth: 160 }} />
      </div>
    </div>
  )
  return (
    <Popover content={panel} trigger="click" placement="bottomLeft">
      <Button className="top-filter">{periodLabel(year, period, selection.compare)} ▾</Button>
    </Popover>
  )
}

function CompanyPicker({ companies, selection, onChange }: Pick<Props, 'companies' | 'selection' | 'onChange'>) {
  const all = selection.companies.length === 0
  const toggle = (id: number) => {
    const chosen = all ? [] : selection.companies
    const next = chosen.includes(id) ? chosen.filter((c) => c !== id) : [...chosen, id]
    onChange({ companies: next.length === companies.length ? [] : next })
  }
  const source = companies[0]?.health.source_name ?? 'the source'
  const chosenNames = companies.filter((c) => selection.companies.includes(c.id)).map((c) => c.name)
  const label = all || chosenNames.length === 0 ? (companies.length > 1 ? 'All combined' : (companies[0]?.name ?? '')) : chosenNames.length === 1 ? chosenNames[0] : `${chosenNames.length} companies`
  const panel = (
    <div className="picker-panel" aria-label="Companies">
      {companies.length > 1 && (
        <button type="button" className={all ? 'chip chip-all active' : 'chip chip-all'} aria-pressed={all} onClick={() => onChange({ companies: [] })}>
          All combined
        </button>
      )}
      <div className="picker-list">
        {companies.map((c) => {
          const chosen = !all && selection.companies.includes(c.id)
          const state = loadedText(c)
          const checked = c.health.source_checked_at
          return (
            <Tooltip key={c.id} placement="right"
              title={checked ? `${state} in ${source} when checked ${timeAgo(checked)} (${c.health.source_checked_by === 'entity_check' ? 'entity check' : 'sync'})` : `${source} not asked yet`}>
              <button type="button" className={chosen ? 'chip active' : 'chip'} aria-pressed={chosen} onClick={() => toggle(c.id)}>
                <span className={`dot dot-${state.replace(' ', '-')}`} aria-hidden />
                {c.name}
                <span className="chip-note">{state}</span>
              </button>
            </Tooltip>
          )
        })}
      </div>
      <p className="picker-note">
        <span className="dot dot-loaded" aria-hidden /> Loaded in {source} <span className="dot dot-not-loaded" aria-hidden /> Not loaded. Several companies
        are combined, without inter-company eliminations.
      </p>
    </div>
  )
  return (
    <Popover content={panel} trigger="click" placement="bottomLeft">
      <Button className="top-filter">Company: {label} ▾</Button>
    </Popover>
  )
}

function FacetPicker({ facet, label, enabled, why, companies, values, onChange }: {
  facet: Facet; label: string; enabled: boolean; why: string; companies: number[]; values: string[]; onChange: (values: string[]) => void
}) {
  const options = useQuery({
    queryKey: ['facet', facet, companies],
    queryFn: () => getJson<FacetValue[]>(`/api/v1/facets/${facet}`, { company: companies }),
    enabled: enabled && companies.length > 0,
  })
  if (!enabled) {
    return (
      <Tooltip title={why}>
        <Button className="top-filter" disabled aria-label={`${label} (not used on this page)`}>{label} ▾</Button>
      </Tooltip>
    )
  }
  return (
    <Select mode="multiple" allowClear showSearch aria-label={label} placeholder={label} className="top-facet" value={values}
      options={(options.data ?? []).map((v) => ({ value: v.value, label: v.value }))} loading={options.isPending}
      onChange={onChange} maxTagCount={1} popupMatchSelectWidth={false} />
  )
}

function CopyLink() {
  const { message } = AntApp.useApp()
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(window.location.href)
      message.success('Link copied: it opens this page with the same selection.')
    } catch {
      message.error("The link couldn't be copied; copy it from the address bar.")
    }
  }
  return (
    <Button className="top-copy" onClick={copy}>
      Copy link
    </Button>
  )
}

export function TopBar(props: Props) {
  return (
    <header className="top-bar">
      <Breadcrumb className="top-crumbs" items={props.crumbs.map((c) => ({
        title: c.path ? <a href={href(c.path, props.query)}>{c.label}</a> : <strong>{c.label}</strong>,
      }))} />
      {props.companies.length > 0 && (
        <div className="top-filters">
          <PeriodPicker selection={props.selection} years={props.years} year={props.year} period={props.period} onChange={props.onChange} />
          <CompanyPicker companies={props.companies} selection={props.selection} onChange={props.onChange} />
          {FACETS.map((f) => (
            <FacetPicker key={f.key} facet={f.key} label={f.label}
              enabled={props.page?.facets.includes(f.key) ?? false}
              why={props.page?.whyNoFacets ?? 'Not used on this page.'}
              companies={props.selectedIds} values={props.selection.facets[f.key]}
              onChange={(values) => props.onChange({ facets: { ...props.selection.facets, [f.key]: values } })} />
          ))}
          <CopyLink />
        </div>
      )}
    </header>
  )
}
