// The Ledger statement page (Books › Ledger statement; ADR-055): one ledger's opening balance,
// each entry of the period (date, voucher type and number opening the voucher, the other
// ledger, narration, debit, credit) with the running balance, and the closing balance, as
// Tally's ledger report. Without a ledger it offers a search by name. Figures:
// core/ledger_statement.py (GET /api/v1/ledgers/{id}/statement); formulas F-LED-001 to F-LED-004.

import { Alert, Input, Typography } from 'antd'
import { useState } from 'react'
import { useLedgers } from '../../api/queries.ts'
import type { Company, LedgerEntryOut, LedgerStatementOut } from '../../api/types.ts'
import { Explained } from '../../components/Explained.tsx'
import { ErrorState } from '../../components/loading/ErrorState.tsx'
import { Loading } from '../../components/loading/Loading.tsx'
import { companyDisplayName } from '../../companyDisplayName.ts'
import { formatDate, formatDrCr as drCr } from '../../format.ts'
import type { ExplorerColumn } from '../../reporting/explorer.ts'
import { ExplorerTable } from '../../reporting/ExplorerTable.tsx'
import { ReportFrame, type PanelProps } from '../../reporting/ReportFrame.tsx'
import type { Query } from '../../router.ts'
import { builtHref } from '../../shell/nav.ts'
import { LEDGER_WORDS } from './notes.ts'


function columns(query: Query): ExplorerColumn<LedgerEntryOut>[] {
  return [
    { key: 'date', label: 'Date', kind: 'date', value: (e) => e.date },
    { key: 'particulars', label: 'Particulars', kind: 'text', value: (e) => e.particulars, wrap: true,
      hint: (e) => (e.voucher_id === null ? LEDGER_WORDS.revaluation : undefined) },
    { key: 'type', label: 'Vch Type', kind: 'text', value: (e) => e.voucher_type, groupable: true },
    { key: 'number', label: 'Vch No.', kind: 'text', value: (e) => e.number,
      link: (e) => (e.voucher_id !== null ? builtHref(['books', 'vouchers', String(e.voucher_id)], query) : undefined) },
    { key: 'narration', label: 'Narration', kind: 'text', value: (e) => e.narration, wrap: true },
    { key: 'debit', label: 'Debit', kind: 'amount', value: (e) => e.debit, formula: 'F-LED-002' },
    { key: 'credit', label: 'Credit', kind: 'amount', value: (e) => e.credit, formula: 'F-LED-002' },
    { key: 'balance', label: 'Balance', kind: 'amount', value: (e) => e.balance, render: (e) => drCr(e.balance), summed: false, formula: 'F-LED-003' },
  ]
}

interface StatementProps extends PanelProps {
  companies: Company[]
  statement: LedgerStatementOut | undefined
  loading: boolean
  error: Error | null
  onRetry?: () => void
}

function help(sourceName: string) {
  return (
    <>
      <p>
        One ledger's opening balance, every entry of the period with the other ledger and the running balance, and its closing balance
        (F-LED-001 to F-LED-004). An income or expense ledger starts each financial year at nil, as in {sourceName}.
      </p>
      <p>
        <strong>To compare with {sourceName}:</strong> Display More Reports → Account Books → Ledger, the same ledger and dates.
      </p>
    </>
  )
}

export function LedgerStatement(props: StatementProps) {
  const { statement } = props
  let content: React.ReactNode
  if (props.error) {
    content = <ErrorState message="The ledger statement couldn't be loaded." error={props.error} onRetry={props.onRetry} />
  } else if (props.loading || !statement) {
    content = <Loading shape="report" />
  } else {
    const company = props.companies.find((c) => c.id === statement.company)
    content = (
      <section className="card" aria-label="Ledger statement">
        <Typography.Text type="secondary">
          {[...statement.groups, company ? companyDisplayName(company) : undefined].filter(Boolean).join(' · ')}
        </Typography.Text>
        <p className="report-note" data-figure="opening" data-formula="F-LED-001">
          <Explained label={LEDGER_WORDS.opening} help="The balance before the period (F-LED-001)." /> on {formatDate(statement.period_start)}: {drCr(statement.opening)}
        </p>
        {statement.truncated && <Alert type="warning" showIcon message={LEDGER_WORDS.truncated} />}
        <ExplorerTable id="ledger-statement" label="Ledger statement" columns={columns(props.query)} rows={statement.entries}
          rowKey={(e) => `${e.voucher_id ?? 'calc'}-${e.date}`} pageSize={500} totalLabel="Total" />
        <p className="report-note" data-figure="closing" data-formula="F-LED-004">
          <Explained label={LEDGER_WORDS.closing} help="The opening plus the period's debits less its credits (F-LED-004)." /> on {formatDate(statement.period_end)}: {drCr(statement.closing)}
        </p>
      </section>
    )
  }
  return (
    <ReportFrame {...props} title={statement?.name ?? 'Ledger statement'} page="ledger-statement" period={undefined}
      dateRange={statement ? { start: statement.period_start, end: statement.period_end } : undefined} combined={false} help={help}>
      {content}
    </ReportFrame>
  )
}

/** Without a ledger: find one by its name. */
export function LedgerPicker({ companies, companyIds, query }: { companies: Company[]; companyIds: number[]; query: Query }) {
  const [text, setText] = useState('')
  const found = useLedgers(companyIds, text)
  const names = new Map(companies.map((c) => [c.id, companyDisplayName(c)]))
  const several = companyIds.length > 1
  return (
    <ReportFrame query={query} title="Ledger statement" page="ledger-statement" companies={companies} period={undefined} combined={false} help={help}>
      <section className="card" aria-label="Find a ledger">
        <Input.Search aria-label={LEDGER_WORDS.pick} placeholder={LEDGER_WORDS.pickHelp} allowClear value={text} onChange={(e) => setText(e.target.value)} />
        {found.isPending ? (
          <Loading shape="report" />
        ) : found.error ? (
          <ErrorState message="The ledgers couldn't be loaded." error={found.error} onRetry={() => void found.refetch()} />
        ) : (found.data ?? []).length === 0 ? (
          <p className="muted">{LEDGER_WORDS.none}</p>
        ) : (
          <ul className="ledger-list" aria-label="Ledgers">
            {(found.data ?? []).map((l) => (
              <li key={l.ledger_id}>
                <a href={builtHref(['books', 'ledger', String(l.ledger_id)], query)}>{l.name}</a>{' '}
                <span className="muted">
                  {l.group}
                  {several ? ` · ${names.get(l.company) ?? ''}` : ''}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </ReportFrame>
  )
}
