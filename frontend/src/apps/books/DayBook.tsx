// The Day Book page (Books › Day Book; ADR-057): every voucher of the period as Tally's Day
// Book lists it (date, Particulars, voucher type, the amount in the Debit or Credit column, or
// a stock voucher's quantity), with its number opening the voucher page; filters by voucher
// type and party; tags for vouchers that don't change the books; the vouchers of each type.
// Figures: core/day_book.py (GET /api/v1/day-book); formulas F-DAY-001, F-DAY-002.

import { Alert, Select, Tag } from 'antd'
import type { Company, DayBookOut, DayBookRowOut } from '../../api/types.ts'
import { ErrorState } from '../../components/loading/ErrorState.tsx'
import { Loading } from '../../components/loading/Loading.tsx'
import { companyDisplayName } from '../../companyDisplayName.ts'
import type { ExplorerColumn } from '../../reporting/explorer.ts'
import { ExplorerTable } from '../../reporting/ExplorerTable.tsx'
import { ReportFrame, type PanelProps } from '../../reporting/ReportFrame.tsx'
import type { Query } from '../../router.ts'
import { builtHref } from '../../shell/nav.ts'
import { DAY_BOOK_WORDS as W } from './notes.ts'

interface Props extends PanelProps {
  companies: Company[]
  found: DayBookOut | undefined
  loading: boolean
  error: Error | null
  onRetry?: () => void
  voucherTypes: string[] // the filters chosen
  parties: string[]
  onFilters: (change: { voucherTypes?: string[]; parties?: string[] }) => void
}

/** A stock voucher's quantity as Tally writes it: "3 Nos", "(-)2 Nos". */
function quantity(value: string | null | undefined, unit: string | null | undefined): string | null {
  if (value === null || value === undefined) return null
  const number = Number(value)
  const text = `${Math.abs(number).toLocaleString('en-IN', { maximumFractionDigits: 4 })}${unit ? ` ${unit}` : ''}`
  return number < 0 ? `(-)${text}` : text
}

function columns(names: Map<number, string>, combined: boolean, query: Query): ExplorerColumn<DayBookRowOut>[] {
  return [
    { key: 'date', label: 'Date', kind: 'date', value: (r) => r.date },
    { key: 'particulars', label: 'Particulars', kind: 'text', value: (r) => r.particulars, wrap: true },
    {
      key: 'type', label: 'Vch Type', kind: 'text', value: (r) => r.voucher_type, groupable: true,
      render: (r) => (
        <>
          {r.voucher_type}
          {r.tags.map((t) => (
            <Tag key={t} className="day-book-tag" title={W.tags[t as keyof typeof W.tags]}>{t}</Tag>
          ))}
        </>
      ),
    },
    { key: 'number', label: 'Vch No.', kind: 'text', value: (r) => r.number, link: (r) => builtHref(['books', 'vouchers', String(r.voucher_id)], query) },
    { key: 'company', label: 'Company', kind: 'text', value: (r) => names.get(r.company) ?? `Company ${r.company}`, groupable: true, hidden: !combined },
    { key: 'debit', label: 'Debit', kind: 'amount', value: (r) => r.debit, formula: 'F-DAY-001' },
    { key: 'credit', label: 'Credit', kind: 'amount', value: (r) => r.credit, formula: 'F-DAY-001' },
    { key: 'inward', label: 'Inwards Qty', kind: 'text', value: (r) => quantity(r.inward, r.unit), formula: 'F-DAY-001' },
    { key: 'outward', label: 'Outwards Qty', kind: 'text', value: (r) => quantity(r.outward, r.unit), formula: 'F-DAY-001' },
    { key: 'narration', label: 'Narration', kind: 'text', value: (r) => r.narration, wrap: true },
    { key: 'party', label: 'Party', kind: 'text', value: (r) => r.party, groupable: true, hidden: true },
  ]
}

function help(sourceName: string) {
  return (
    <>
      <p>{W.help}</p>
      <p>
        <strong>To compare with {sourceName}:</strong> {W.compare}
      </p>
    </>
  )
}

export function DayBook(props: Props) {
  const { found } = props
  const names = new Map(props.companies.map((c) => [c.id, companyDisplayName(c)]))
  let content: React.ReactNode
  if (props.error) {
    content = <ErrorState message="The Day Book couldn't be loaded." error={props.error} onRetry={props.onRetry} />
  } else if (props.loading || !found) {
    content = <Loading shape="report" />
  } else {
    content = (
      <>
        <section className="card" aria-label="Day Book filters">
          <div className="day-book-filters">
            <Select mode="multiple" allowClear aria-label={W.typeFilter} placeholder={W.typeFilter} value={props.voucherTypes}
              options={found.voucher_types.map((t) => ({ value: t, label: t }))} onChange={(v: string[]) => props.onFilters({ voucherTypes: v })} />
            <Select mode="multiple" allowClear aria-label={W.partyFilter} placeholder={W.partyFilter} value={props.parties}
              options={found.parties.map((p) => ({ value: p, label: p }))} onChange={(v: string[]) => props.onFilters({ parties: v })} />
          </div>
          {found.truncated && <Alert type="warning" showIcon message={W.truncated} />}
          <ExplorerTable id="day-book" label="Day Book" columns={columns(names, props.companies.length > 1, props.query)} rows={found.rows}
            rowKey={(r) => String(r.voucher_id)} pageSize={500} totalLabel="Total" />
          <p className="card-note">{W.tagNote}</p>
        </section>
        <section className="card" aria-label={W.countsTitle}>
          <h2 className="card-title">{W.countsTitle}</h2>
          <table className="report-table compact" aria-label={W.countsTitle}>
            <thead>
              <tr>
                <th scope="col">Vch Type</th>
                <th scope="col" className="num">Vouchers</th>
              </tr>
            </thead>
            <tbody>
              {found.counts.map((c) => (
                <tr key={c.voucher_type} data-figure="count" data-formula="F-DAY-002">
                  <th scope="row">{c.voucher_type}</th>
                  <td className="num">{c.vouchers.toLocaleString('en-IN')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      </>
    )
  }
  return (
    <ReportFrame {...props} title="Day Book" page="day-book" period={undefined}
      dateRange={found ? { start: found.period_start, end: found.period_end } : undefined} combined={props.companies.length > 1} help={help}>
      {content}
    </ReportFrame>
  )
}
