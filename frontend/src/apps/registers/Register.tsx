// The Sales register and the Purchase register (docs/design/dashboard.md Section 0.2), Day
// Book style: Date, Particulars (the first ledger entry), Vch Type, Vch No., Debit, Credit,
// Narration; grouped by month with subtotals and the grand total, in the table explorer. Sales
// with credit notes, purchases with debit notes. Rows: core/registers.py
// (GET /api/v1/registers/{side}).

import { Alert, Skeleton, Typography } from 'antd'
import type { Company, RegisterOut, RegisterRowOut } from '../../api/types.ts'
import { formatDate, formatMonth } from '../../format.ts'
import { companyDisplayName } from '../../companyDisplayName.ts'
import type { ExplorerColumn } from '../../reporting/explorer.ts'
import { ExplorerTable } from '../../reporting/ExplorerTable.tsx'
import { WhatIsThis } from '../../reporting/WhatIsThis.tsx'
import type { Query } from '../../router.ts'
import { builtHref } from '../../shell/nav.ts'
import { COMBINED_NOTE } from '../dashboard/words.ts'

export type Side = 'sales' | 'purchases'

const WORDS: Record<Side, { title: string; group: string; returns: string; ledgers: string; value: string; party: string }> = {
  sales: { title: 'Sales register', group: 'Sales Accounts', returns: 'credit notes', ledgers: 'sales', value: 'Sales value', party: 'customer' },
  purchases: { title: 'Purchase register', group: 'Purchase Accounts', returns: 'debit notes', ledgers: 'purchase', value: 'Purchase value', party: 'vendor' },
}

interface Props {
  side: Side
  companies: Company[] // the selected ones
  register: RegisterOut | undefined
  loading: boolean
  error: Error | null
  query: Query
}

/** A party opens their page once built; on the Sales register, until then, the register
 *  filtered to that customer. */
function partyHref(side: Side, r: RegisterRowOut, query: Query): string | undefined {
  if (r.party_id === null || !r.party) return undefined
  const page = side === 'sales' ? ['sales', 'customers', String(r.party_id)] : ['purchases', 'vendors', String(r.party_id)]
  return builtHref(page, query) ?? (side === 'sales' ? builtHref(['sales', 'register'], { ...query, customer: [r.party] }) : undefined)
}

function registerColumns(side: Side, names: Map<number, string>, combined: boolean, query: Query): ExplorerColumn<RegisterRowOut>[] {
  const words = WORDS[side]
  return [
    { key: 'month', label: 'Month', kind: 'text', value: (r) => formatMonth(r.date), groupable: true, hidden: true },
    { key: 'date', label: 'Date', kind: 'date', value: (r) => r.date },
    {
      key: 'particulars',
      label: 'Particulars',
      kind: 'text',
      value: (r) => r.particulars,
      link: (r) => builtHref(['books', 'ledgers', String(r.ledger_id)], query) ?? (r.particulars === r.party ? partyHref(side, r, query) : undefined),
    },
    { key: 'type', label: 'Vch Type', kind: 'text', value: (r) => r.voucher_type, groupable: true },
    { key: 'number', label: 'Vch No.', kind: 'text', value: (r) => r.number, link: (r) => builtHref(['books', 'vouchers', String(r.voucher_id)], query) },
    { key: 'debit', label: 'Debit', kind: 'amount', value: (r) => r.debit },
    { key: 'credit', label: 'Credit', kind: 'amount', value: (r) => r.credit },
    { key: 'narration', label: 'Narration', kind: 'text', value: (r) => r.narration },
    { key: 'reference', label: 'Reference', kind: 'text', value: (r) => r.reference ?? null, hidden: true },
    { key: 'instrument', label: 'Cheque / transfer no.', kind: 'text', value: (r) => r.instrument_number ?? null, hidden: true },
    { key: 'utr', label: 'UTR', kind: 'text', value: (r) => r.transaction_reference ?? null, hidden: true },
    { key: 'party', label: words.party === 'customer' ? 'Customer' : 'Vendor', kind: 'text', value: (r) => r.party, link: (r) => partyHref(side, r, query), groupable: true, hidden: true },
    { key: 'value', label: words.value, kind: 'amount', value: (r) => r.side_value, hidden: true },
    { key: 'company', label: 'Company', kind: 'text', value: (r) => names.get(r.company) ?? `Company ${r.company}`, groupable: true, hidden: !combined },
  ]
}

function Help({ side, sourceName }: { side: Side; sourceName: string }) {
  const w = WORDS[side]
  return (
    <>
      <p>
        Every {side === 'sales' ? 'sales voucher' : 'purchase voucher'} and {w.returns} of the companies and period you chose, the way {sourceName}'s Day
        Book shows them: the date, the first ledger of the voucher (for an invoice, the {w.party}), its type and number, the amount as a debit or a
        credit, and the narration. Grouped by month with subtotals and the grand total; group by voucher type, {w.party} or company instead with Group
        by.
      </p>
      <p>
        <strong>{w.value}</strong> (under Columns) is what each voucher puts on the ledgers under {w.group}, before taxes; {w.returns} are negative.
        Its total for a month is the month's gross {w.ledgers}s less returns. Cancelled and optional vouchers aren't listed.
      </p>
      <p>
        <strong>To compare with {sourceName}:</strong> Display More Reports → Account Books → {side === 'sales' ? 'Sales Register' : 'Purchase Register'}{' '}
        (and {side === 'sales' ? 'Credit Note Register' : 'Debit Note Register'} for the returns), choose a month: the same vouchers, amounts and
        totals.
      </p>
    </>
  )
}

export function Register(props: Props) {
  const { side, register, companies, query } = props
  const words = WORDS[side]
  const sourceName = companies[0]?.health.source_name ?? 'the source'
  const names = new Map(companies.map((c) => [c.id, companyDisplayName(c)]))
  const title = companies.map(companyDisplayName).join(' + ')

  let content: React.ReactNode
  if (props.error) {
    content = <Alert type="error" showIcon message={`The ${words.title.toLowerCase()} couldn't be loaded.`} description={props.error.message} />
  } else if (props.loading || !register) {
    content = <Skeleton active paragraph={{ rows: 12 }} />
  } else {
    content = (
      <>
        {register.truncated && (
          <Alert
            type="warning"
            showIcon
            message={`Only the first ${register.rows.length.toLocaleString('en-IN')} vouchers are shown: choose fewer months to see them all.`}
          />
        )}
        <ExplorerTable
          id={`${side}-register`}
          label={words.title}
          columns={registerColumns(side, names, register.combined, query)}
          rows={register.rows}
          rowKey={(r) => String(r.voucher_id)}
          groupBy="month"
          pageSize={500}
          totalLabel="Grand total"
        />
      </>
    )
  }

  return (
    <div className="report-page">
      <div className="report-main">
        <div className="report-head">
          <div>
            <Typography.Title level={2} className="report-title">
              {words.title} · {title}
            </Typography.Title>
            {register && (
              <Typography.Text type="secondary">
                {formatDate(register.period.start)} to {formatDate(register.period.end)}
                {register.combined ? ` · ${COMBINED_NOTE}` : ''}
              </Typography.Text>
            )}
          </div>
          <div className="report-toolbar"><WhatIsThis><Help side={side} sourceName={sourceName} /></WhatIsThis></div>
        </div>
        {content}
      </div>
    </div>
  )
}
