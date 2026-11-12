// The page header under the top bar (docs/design/dashboard.md Section 0.4, ADR-050): the
// breadcrumbs, the page's title with its period and comparison, the segment chips (all
// companies or any combination, each marked loaded or not loaded in the source as last checked:
// the dashboard never asks), the facets the page applies (channels as chips on the Sales pages,
// the others as pickers), "Updated N min ago" from the last sync, Copy link, and the module's
// pages as tabs.

import { useQuery } from '@tanstack/react-query'
import { App as AntApp, Breadcrumb, Button, Select, Tooltip } from 'antd'
import { getJson } from '../api/client.ts'
import type { Company, FacetValue } from '../api/types.ts'
import { timeAgo } from '../format.ts'
import { companyDisplayName } from '../companyDisplayName.ts'
import { href, type Query } from '../router.ts'
import { periodText, type Change, type PeriodChoice, type Selection } from '../selection.ts'
import type { Facet, NavGroup, NavPage } from './nav.ts'
import { lastSync, syncStatus } from './status.ts'

export interface Crumb {
  label: string
  path?: string[] // omitted for the current page
}

interface Props {
  crumbs: Crumb[]
  title: string
  group: NavGroup | undefined // the module, for its page tabs
  page: NavPage | undefined
  companies: Company[] // every visible company
  selection: Selection
  selectedIds: number[]
  period: PeriodChoice | undefined
  onChange: Change
  query: Query
}

const FACET_LABELS: Record<Facet, string> = {
  customer: 'Customer',
  channel: 'Channel',
  ledger_group: 'Ledger group',
  voucher_type: 'Voucher type',
}
const MAX_CHIPS = 8 // more values than this: a picker instead of chips

function loadedText(c: Company): string {
  if (c.health.source_loaded === null || c.health.source_loaded === undefined) return 'not checked'
  return c.health.source_loaded ? 'loaded' : 'not loaded'
}

/** "All" plus a chip per value; several can be chosen, all of them is "All". */
function Chips({ label, all, items, chosen, onChange }: {
  label: string
  all: string
  items: { value: string; text: string; note?: string; tip?: string; dot?: string }[]
  chosen: string[]
  onChange: (chosen: string[]) => void
}) {
  const none = chosen.length === 0
  const toggle = (value: string) => {
    const next = chosen.includes(value) ? chosen.filter((v) => v !== value) : [...chosen, value]
    onChange(next.length === items.length ? [] : next)
  }
  return (
    <div className="segment-chips" role="group" aria-label={label}>
      {items.length > 1 && (
        <button type="button" className={none ? 'chip chip-all active' : 'chip chip-all'} aria-pressed={none} onClick={() => onChange([])}>
          {all}
        </button>
      )}
      {items.map((item) => {
        const active = !none && chosen.includes(item.value)
        const chip = (
          <button key={item.value} type="button" className={active ? 'chip active' : 'chip'} aria-pressed={active} onClick={() => toggle(item.value)}>
            {item.dot && <span className={`dot dot-${item.dot}`} aria-hidden />}
            {item.text}
            {item.note && <span className="chip-note">{item.note}</span>}
          </button>
        )
        return item.tip ? (
          <Tooltip key={item.value} title={item.tip}>
            {chip}
          </Tooltip>
        ) : (
          chip
        )
      })}
    </div>
  )
}

function CompanyChips({ companies, selection, onChange }: Pick<Props, 'companies' | 'selection' | 'onChange'>) {
  const source = companies[0]?.health.source_name ?? 'the source'
  return (
    <Chips label="Companies" all="All companies" chosen={selection.companies.map(String)}
      onChange={(chosen) => onChange({ companies: chosen.map(Number) })}
      items={companies.map((c) => {
        const state = loadedText(c)
        const checked = c.health.source_checked_at
        return {
          value: String(c.id),
          text: companyDisplayName(c),
          dot: state.replace(' ', '-'),
          tip: checked ? `${state} in ${source} when checked ${timeAgo(checked)}. Several companies are combined, without inter-company eliminations.` : `${source} not asked yet`,
        }
      })} />
  )
}

function FacetFilter({ facet, companies, values, onChange }: { facet: Facet; companies: number[]; values: string[]; onChange: (values: string[]) => void }) {
  const options = useQuery({
    queryKey: ['facet', facet, companies],
    queryFn: () => getJson<FacetValue[]>(`/api/v1/facets/${facet}`, { company: companies }),
    enabled: companies.length > 0,
  })
  const label = FACET_LABELS[facet]
  const found = options.data ?? []
  if (facet === 'channel' && found.length > 0 && found.length <= MAX_CHIPS) {
    return <Chips label="Channels" all="All channels" chosen={values} onChange={onChange} items={found.map((v) => ({ value: v.value, text: v.value }))} />
  }
  return (
    <Select mode="multiple" allowClear showSearch aria-label={label} placeholder={label} className="header-facet" value={values}
      options={found.map((v) => ({ value: v.value, label: v.value }))} loading={options.isPending}
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
    <Button size="small" className="header-copy" onClick={copy}>
      Copy link
    </Button>
  )
}

function Updated({ companies }: { companies: Company[] }) {
  const status = syncStatus(companies)
  const synced = lastSync(companies)
  if (!status) return null
  return (
    <Tooltip title={status.text}>
      <span className={status.ok ? 'header-updated' : 'header-updated header-updated-bad'}>
        <span className="dot" aria-hidden /> {synced ? `Updated ${timeAgo(synced)}` : 'Never synced'}
      </span>
    </Tooltip>
  )
}

export function PageHeader(props: Props) {
  const tabs = props.group?.pages.filter((p) => p.built && !p.detail) ?? []
  const facets = props.page?.facets ?? []
  return (
    <section className="page-header" aria-label="Page">
      <Breadcrumb className="header-crumbs" items={props.crumbs.map((c) => ({
        title: c.path ? <a href={href(c.path, props.query)}>{c.label}</a> : <span>{c.label}</span>,
      }))} />
      <div className="header-row">
        <div className="header-title">
          <h1>{props.title}</h1>
          <p className="header-period">{periodText(props.period, props.selection)}</p>
        </div>
        {props.companies.length > 0 && (
          <div className="header-right">
            <CompanyChips companies={props.companies} selection={props.selection} onChange={props.onChange} />
            <Updated companies={props.companies} />
            <CopyLink />
          </div>
        )}
      </div>
      {facets.length > 0 && (
        <div className="header-facets">
          {facets.map((f) => (
            <FacetFilter key={f} facet={f} companies={props.selectedIds} values={props.selection.facets[f]}
              onChange={(values) => props.onChange({ facets: { ...props.selection.facets, [f]: values } })} />
          ))}
        </div>
      )}
      {tabs.length > 1 && props.group && (
        <nav className="header-tabs" aria-label={`${props.group.label} pages`}>
          {tabs.map((p) => {
            const active = props.page?.key === p.key
            return (
              <a key={p.key} href={href([props.group!.key, p.key], props.query)} className={active ? 'header-tab active' : 'header-tab'} aria-current={active ? 'page' : undefined}>
                {p.label}
              </a>
            )
          })}
        </nav>
      )}
    </section>
  )
}
