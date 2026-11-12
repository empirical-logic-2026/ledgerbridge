// The Data module (docs/design/dashboard.md Section 0.4): Data health (each visible company's
// last sync, whether its latest checks against the source passed and up to which date, and
// whether the source had it loaded when last asked, with key cards and status pills) and
// Companies (each company's code, books from and financial year). Counts and states only; from
// GET /api/v1/companies (v_data_health). Companies on hold aren't shown.

import { Typography } from 'antd'
import type { Company } from '../../api/types.ts'
import { KeyCard } from '../../components/KeyCard.tsx'
import { StatusPill } from '../../components/StatusPill.tsx'
import { formatDate, timeAgo } from '../../format.ts'
import { companyDisplayName } from '../../companyDisplayName.ts'
import type { ExplorerColumn } from '../../reporting/explorer.ts'
import { ExplorerTable } from '../../reporting/ExplorerTable.tsx'
import { lastSync } from '../../shell/status.ts'
import { tokens } from '../../theme.ts'
import { sourceStatusInfo, validationStatusInfo } from '../../statuses.ts'

const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']

const HEALTH: ExplorerColumn<Company>[] = [
  { key: 'name', label: 'Company', kind: 'text', value: companyDisplayName },
  { key: 'synced', label: 'Last sync', kind: 'text', value: (c) => (c.health.last_sync_at ? timeAgo(c.health.last_sync_at) : 'Never') },
  {
    key: 'checks',
    help: 'Hover a status to see what it means.',
    label: 'Status',
    kind: 'text',
    groupable: true,
    value: (c) => validationStatusInfo(c.health.validation_status).label,
    render: (c) => {
      const status = validationStatusInfo(c.health.validation_status)
      return <StatusPill text={status.label} tone={status.tone} help={status.meaning} />
    },
  },
  { key: 'checked_to', label: 'Checked up to', kind: 'date', value: (c) => c.health.validated_as_of },
  {
    key: 'loaded',
    help: 'Hover a status to see what it means.',
    label: 'Source status',
    kind: 'text',
    groupable: true,
    value: (c) => sourceStatusInfo(c.health.source_loaded).label,
    render: (c) => {
      const status = sourceStatusInfo(c.health.source_loaded)
      return <StatusPill text={status.label} tone={status.tone} help={status.meaning} />
    },
  },
]

const COMPANIES: ExplorerColumn<Company>[] = [
  { key: 'name', label: 'Company', kind: 'text', value: companyDisplayName },
  { key: 'code', label: 'Code', kind: 'text', value: (c) => c.code },
  { key: 'books_from', label: 'Books from', kind: 'date', value: (c) => c.books_from },
  { key: 'fy', label: 'Financial year starts', kind: 'text', value: (c) => MONTHS[c.fy_start_month - 1] ?? '' },
  { key: 'source', label: 'Source', kind: 'text', value: (c) => c.health.source_name, groupable: true },
]

export function DataHealth({ companies, dark }: { companies: Company[]; dark: boolean }) {
  const colours = tokens[dark ? 'dark' : 'light']
  const [green, charcoal, lighter, grey] = colours.accents
  const synced = lastSync(companies)
  const count = (test: (c: Company) => boolean) => String(companies.filter(test).length)
  return (
    <>
      <div className="sales-cards">
        <KeyCard label="Companies" formula="F-DAT-001" figure={{ value: String(companies.length) }} unit="count" note="Shown (companies on hold aren't)" accent={grey} />
        <KeyCard label="Checks passed" formula="F-DAT-002" figure={{ value: count((c) => c.health.validation_status === 'passed') }} unit="count" note={`of ${companies.length}`} accent={green} />
        <KeyCard label="Loaded in the source" formula="F-DAT-003" figure={{ value: count((c) => c.health.source_loaded === true) }} unit="count" note={`of ${companies.length}, as last asked`} accent={lighter} />
        <KeyCard label="Last sync" formula="F-DAT-004" figure={{ value: null }} missing="Never synced" note={synced ? `${timeAgo(synced)}, ${formatDate(synced.slice(0, 10))}` : 'Never synced'} accent={charcoal} />
      </div>
      <section className="card" aria-label="Data health by company">
        <ExplorerTable id="data-health" label="Data health by company" columns={HEALTH} rows={companies} rowKey={(c) => String(c.id)} />
        <Typography.Text type="secondary">
          The checks compare our books and statements with the source's own (<code>./dev.ps1 validate</code>); "In the source" is whether the source
          had the company loaded when last asked (a sync or <code>./dev.ps1 entity-check</code>). The dashboard never asks the source itself.
        </Typography.Text>
      </section>
    </>
  )
}

export function CompaniesPage({ companies }: { companies: Company[] }) {
  return (
    <section className="card" aria-label="Companies">
      <ExplorerTable id="data-companies" label="Companies" columns={COMPANIES} rows={companies} rowKey={(c) => String(c.id)} />
    </section>
  )
}
