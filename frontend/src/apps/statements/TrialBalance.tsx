// The Trial Balance page (P&L & KPIs › Trial Balance; ADR-055): every group with its debit or
// credit at the period's statement date, for the financial year that date falls in, with the
// totals at the bottom, as Tally's Trial Balance. Condensed shows the groups; Detailed opens
// every group to its sub-groups and ledgers (Tally's Alt+F1); a group opens and closes on its
// own too. A ledger opens its Ledger statement. Figures: core/trial_balance.py (GET
// /api/v1/reports/trial-balance); formulas F-TB-001 to F-TB-005.

import { Alert, Segmented, Typography } from 'antd'
import { useState } from 'react'
import type { Company, TrialBalanceOut, TrialBalanceRowOut } from '../../api/types.ts'
import { AccountTree } from '../../components/AccountTree.tsx'
import { openable, type TreeRow } from '../../components/accountTree.ts'
import { Explained } from '../../components/Explained.tsx'
import { ErrorState } from '../../components/loading/ErrorState.tsx'
import { Loading } from '../../components/loading/Loading.tsx'
import { Money } from '../../components/Money.tsx'
import { formatDate } from '../../format.ts'
import { ReportFrame, type PanelProps } from '../../reporting/ReportFrame.tsx'
import type { Query } from '../../router.ts'
import { builtHref, ledgerHref } from '../../shell/nav.ts'
import { TB_WORDS } from './notes.ts'

interface Props extends PanelProps {
  companies: Company[]
  report: TrialBalanceOut | undefined
  loading: boolean
  error: Error | null
  onRetry?: () => void
  detailed: boolean
  onDetailed: (detailed: boolean) => void
}

/** A blank cell for nothing, as Tally leaves it. */
function Side({ value }: { value: string }) {
  return Number(value) === 0 ? null : <Money value={value} />
}

function treeRow(row: TrialBalanceRowOut, query: Query): TreeRow {
  return {
    key: row.key,
    label: row.label,
    kind: row.kind,
    depth: row.depth,
    parent: row.parent ?? null,
    cells: [<Side key="d" value={row.debit} />, <Side key="c" value={row.credit} />],
    to: row.kind === 'stock' ? builtHref(['stock', 'summary'], query) : ledgerHref(row.ledger_id, query),
    formula: 'F-TB-001',
  }
}

function Table({ report, detailed, query }: { report: TrialBalanceOut; detailed: boolean; query: Query }) {
  const lines = report.rows.filter((r) => r.kind !== 'difference')
  const rows = lines.map((r) => treeRow(r, query))
  const [open, setOpen] = useState<Set<string>>(() => (detailed ? openable(rows) : new Set()))
  const toggle = (key: string) =>
    setOpen((now) => {
      const next = new Set(now)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  const difference = report.rows.find((r) => r.kind === 'difference')
  const total = (key: string, label: string, debit: string, credit: string): TreeRow => ({
    key, label, kind: 'total', depth: 0, parent: null, formula: 'F-TB-002',
    cells: [<Money key="d" value={debit} />, <Money key="c" value={credit} />],
  })  // prettier-ignore
  const footer = [total('total', 'Total', report.total_debit, report.total_credit)]
  if (difference) {
    footer.push({ ...treeRow(difference, query), formula: 'F-TB-002' })
    const grand = (a: string, b: string) => (Number(a) + Number(b)).toFixed(2)
    footer.push(total('grand', 'Grand Total', grand(report.total_debit, difference.debit), grand(report.total_credit, difference.credit)))
  }
  return (
    <AccountTree
      label="Trial Balance"
      columns={[
        { label: 'Particulars' },
        { label: <Explained label="Debit" help="Debit balances at the date. A group splits its ledgers into the two columns." /> },
        { label: <Explained label="Credit" help="Credit balances at the date." /> },
      ]}
      rows={rows}
      open={open}
      onToggle={toggle}
      footer={footer}
    />
  )
}

function help(sourceName: string) {
  return (
    <>
      <p>{TB_WORDS.help}</p>
      <p>
        <strong>To compare with {sourceName}:</strong> {TB_WORDS.compare}
      </p>
    </>
  )
}

export function TrialBalance(props: Props) {
  const { report } = props
  let content: React.ReactNode
  if (props.error) {
    content = <ErrorState message="The Trial Balance couldn't be loaded." error={props.error} onRetry={props.onRetry} />
  } else if (props.loading || !report) {
    content = <Loading shape="statement" />
  } else if (report.reason || !report.as_of) {
    content = <Alert type="info" showIcon message="No Trial Balance for this period." description={`${report.reason ?? 'No statement is stored'}.`} />
  } else {
    const from = report.year_start ? formatDate(report.year_start) : TB_WORDS.booksBeginning
    content = (
      <section className="card" aria-label="The Trial Balance">
        <div className="card-head">
          <Typography.Text strong>
            {TB_WORDS.asAt} {formatDate(report.as_of)} · {TB_WORDS.yearFrom} {from}
          </Typography.Text>
          <Segmented
            aria-label="Rows"
            size="small"
            value={props.detailed ? 'detailed' : 'condensed'}
            onChange={(v) => props.onDetailed(v === 'detailed')}
            options={[
              { value: 'condensed', label: 'Condensed' },
              { value: 'detailed', label: 'Detailed' },
            ]}
          />
        </div>
        {report.settings_missing && <Alert type="warning" showIcon message={TB_WORDS.settingsMissing} />}
        <Table key={props.detailed ? 'detailed' : 'condensed'} report={report} detailed={props.detailed} query={props.query} />
        {report.unproved.length > 0 && <p className="card-note">{TB_WORDS.unproved}</p>}
        {report.combined && <Typography.Text type="secondary">Several companies combined, without inter-company eliminations.</Typography.Text>}
      </section>
    )
  }
  return (
    <ReportFrame
      {...props}
      title="Trial Balance"
      page="trial-balance"
      period={undefined}
      dateRange={report ? { start: report.period_start, end: report.period_end, balanceSheet: true } : undefined}
      combined={report?.combined ?? false}
      help={help}
    >
      {content}
    </ReportFrame>
  )
}
