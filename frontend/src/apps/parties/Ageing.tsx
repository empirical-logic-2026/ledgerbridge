// Receivables and payables with ageing (docs/design/dashboard.md Section 0.4; RPT-004): a note
// on how ageing is worked out; key cards (total outstanding, overdue, over 90 days, average
// days to pay); the outstanding bills in six buckets as horizontal bars, aged by days past the
// due date or since the bill date; what isn't in bills, in four parts with what each means;
// every customer (vendor) with its buckets and status, each name opening its page; and every
// open bill, each opening its voucher. As at the period's end; the total equals the Sundry
// Debtors (Creditors) balance on the Balance Sheet. Figures: core/ageing.py
// (GET /api/v1/ageing/{kind}); formulas F-PTY-001 to F-PTY-005 and F-PTY-013 to F-PTY-020.

import { Typography } from 'antd'
import type { AgeingOut, AgeingRowOut, Company, OpenBillOut } from '../../api/types.ts'
import { HBars } from '../../components/HBars.tsx'
import { KeyCard } from '../../components/KeyCard.tsx'
import { ErrorState } from '../../components/loading/ErrorState.tsx'
import { Loading } from '../../components/loading/Loading.tsx'
import { Money } from '../../components/Money.tsx'
import { StatementTable } from '../../components/StatementTable.tsx'
import { formatDate, formatExact, toScaled } from '../../format.ts'
import { fromScaled, type ExplorerColumn } from '../../reporting/explorer.ts'
import { ExplorerTable } from '../../reporting/ExplorerTable.tsx'
import { ReportFrame, type PanelProps } from '../../reporting/ReportFrame.tsx'
import { builtHref } from '../../shell/nav.ts'
import { partyPaymentStatusInfo, statusHint } from '../../statuses.ts'
import { tokens } from '../../theme.ts'
import { BASIS_LABELS, BUCKET_LABELS, NOT_IN_BILLS, type Basis } from './ageingWords.ts'
import { PARTY_WORDS, type PartyKind } from './words.ts'

interface Props extends PanelProps {
  kind: PartyKind
  companies: Company[]
  ageing: AgeingOut | undefined
  loading: boolean
  error: Error | null
  onRetry?: () => void // ask again after an error
  dark: boolean
  basis: Basis
  onBasis: (basis: Basis) => void
}

function percentOf(part: string, whole: string): number | null {
  const all = toScaled(whole)
  return all > 0n ? Number((toScaled(part) * 1000n + all / 2n) / all) / 10 : null // rounded to one decimal
}

function columns(kind: PartyKind, query: PanelProps['query']): ExplorerColumn<AgeingRowOut>[] {
  const w = PARTY_WORDS[kind]
  return [
    { key: 'name', label: w.one, kind: 'text', value: (r) => r.name, link: (r) => builtHref([...w.group, String(r.party_id)], query),
      help: "Hover a row's name to see its payment status and what it means.", hint: (r) => statusHint(partyPaymentStatusInfo(r.payment_status ?? r.status, r.balance, kind)) },
    { key: 'balance', label: w.balance, kind: 'amount', value: (r) => r.balance, formula: 'F-PTY-001' },
    ...BUCKET_LABELS.map(([key, label]): ExplorerColumn<AgeingRowOut> => ({ key, label, kind: 'amount', value: (r) => r.buckets[key], formula: 'F-PTY-014' })),
    { key: 'over_90', label: 'Over 90 days', kind: 'amount', value: (r) => r.over_90, formula: 'F-PTY-018', hidden: true },
    { key: 'uncovered', label: 'Not in bills', kind: 'amount', value: (r) => r.uncovered, formula: 'F-PTY-013' },
  ]
}

const BUCKET_NAME = Object.fromEntries(BUCKET_LABELS)

function billColumns(kind: PartyKind, query: PanelProps['query']): ExplorerColumn<OpenBillOut>[] {
  const w = PARTY_WORDS[kind]
  return [
    { key: 'party', label: w.one, kind: 'text', value: (b) => b.party, link: (b) => builtHref([...w.group, String(b.party_id)], query), groupable: true },
    { key: 'bill', label: 'Bill', kind: 'text', value: (b) => b.bill || '(no name)',
      link: (b) => (b.voucher_id ? builtHref(['books', 'vouchers', String(b.voucher_id)], query) : undefined),
      help: 'The bill opens the voucher that raised it; an opening bill has no voucher.' },
    { key: 'bill_date', label: 'Bill date', kind: 'date', value: (b) => b.bill_date },
    { key: 'due_date', label: 'Due date', kind: 'date', value: (b) => b.due_date },
    { key: 'bucket', label: 'Age', kind: 'text', value: (b) => BUCKET_NAME[b.bucket as keyof AgeingRowOut['buckets']] ?? b.bucket, groupable: true },
    { key: 'days', label: 'Days', kind: 'count', value: (b) => b.days, summed: false, formula: 'F-PTY-014' },
    { key: 'overdue_days', label: 'Days overdue', kind: 'count', value: (b) => b.overdue_days, summed: false, formula: 'F-PTY-005', hidden: true },
    { key: 'amount', label: 'Outstanding', kind: 'amount', value: (b) => b.amount, formula: 'F-PTY-004' },
  ]
}

function help(kind: PartyKind) {
  const receivable = kind === 'customers'
  return (sourceName: string) => (
    <>
      <p>
        Every {receivable ? 'customer' : 'vendor'} with a balance or open bills at the period's end, known by name across the companies you chose.
        The <strong>buckets</strong> are the outstanding bills by days past their due date (or since their bill date): not due, 1–30, 31–60, 61–90,
        91–180 and over 180 days (formula F-PTY-014).
      </p>
      <p>
        <strong>Not in bills</strong> is the balance the bills don't cover, in four parts (F-PTY-013, F-PTY-015 to F-PTY-017, F-PTY-020). The total
        equals the {receivable ? 'Sundry Debtors' : 'Sundry Creditors'} balance on the Balance Sheet.
      </p>
      <p>
        <strong>To compare with {sourceName}:</strong> Display More Reports → Statements of Accounts → Outstandings →{' '}
        {receivable ? 'Receivables' : 'Payables'}, Ageing Analysis, at the same date.
      </p>
    </>
  )
}

function BasisToggle({ basis, onBasis }: { basis: Basis; onBasis: (basis: Basis) => void }) {
  return (
    <div className="ageing-basis" role="group" aria-label="Age bills by">
      <span className="card-small-note">Age by:</span>
      {(Object.keys(BASIS_LABELS) as Basis[]).map((b) => (
        <button key={b} type="button" className={b === basis ? 'chip active' : 'chip'} aria-pressed={b === basis} onClick={() => onBasis(b)}>
          {BASIS_LABELS[b]}
        </button>
      ))}
    </div>
  )
}

function NotInBills({ total }: { total: AgeingRowOut }) {
  const parts = total.not_in_bills
  return (
    <section className="card" aria-label="Not in bills">
      <h2 className="card-title">Not in bills</h2>
      <p className="card-note">The part of the balance that no bill explains, kept apart from the buckets.</p>
      <StatementTable
        label="Not in bills"
        formula="F-PTY-013"
        compared={false}
        compact
        columns={{ label: 'Part', current: 'Amount' }}
        sections={[
          {
            key: 'parts',
            rows: [
              ...NOT_IN_BILLS.map((p) => ({
                key: p.key,
                label: (
                  <>
                    {p.label}
                    <span className="not-in-bills-meaning">{p.meaning}</span>
                  </>
                ),
                current: <Money value={parts[p.key]} />,
                formula: p.formula,
              })),
              { key: 'total', label: 'Total not in bills', kind: 'total' as const, current: <Money value={parts.total} /> },
            ],
          },
        ]}
      />
    </section>
  )
}

export function Ageing(props: Props) {
  const { kind, ageing } = props
  const w = PARTY_WORDS[kind]
  const colours = tokens[props.dark ? 'dark' : 'light']
  let content: React.ReactNode
  if (props.error) {
    content = <ErrorState message="The ageing couldn't be loaded." error={props.error} onRetry={props.onRetry} />
  } else if (props.loading || !ageing) {
    content = <Loading shape="dashboard" />
  } else {
    const t = ageing.total
    const billsText = fromScaled(toScaled(t.balance) - toScaled(t.uncovered))
    const asAt = `As at ${formatDate(ageing.as_of)}`
    const [green, charcoal, lighter, grey] = colours.accents
    const bucketColours = [colours.primary, colours.netProfit, colours.neutralBar, colours.grossProfit, colours.negative, colours.negative]
    content = (
      <>
        <div className="sales-cards">
          <KeyCard label="Total outstanding" formula="F-PTY-001" figure={{ value: t.balance }} note={`${asAt}; = ${w.debtors} on the Balance Sheet`} accent={green} />
          <KeyCard label="Overdue" formula="F-PTY-002" figure={{ value: t.overdue }} note="Past their due date" alert accent={charcoal} />
          <KeyCard label="Over 90 days" formula="F-PTY-018" figure={{ value: t.over_90 }} note={BASIS_LABELS[ageing.basis as Basis]} alert accent={colours.negative} />
          <KeyCard label="Average days to pay" formula="F-PTY-019" figure={{ value: ageing.days_to_pay ?? null }} unit="days" accent={grey}
            note="Bills settled in the period" missing="No bill was settled in the period" />
        </div>
        <section className="card" aria-label="By age">
          <div className="card-head">
            <h2 className="card-title">Outstanding bills by age</h2>
            <BasisToggle basis={props.basis} onBasis={props.onBasis} />
          </div>
          <HBars formula="F-PTY-014" label="Outstanding bills by bucket"
            bars={BUCKET_LABELS.map(([key, label], i) => ({ label, amount: t.buckets[key], share: percentOf(t.buckets[key], billsText), colour: bucketColours[i] }))} />
          <p className="card-note">
            Bills total {formatExact(billsText)}; the balance due is {formatExact(t.balance)}; the rest isn't in bills (below).
          </p>
        </section>
        <NotInBills total={t} />
        <section className="card" aria-label={`${w.title} by ageing`}>
          <ExplorerTable id={`${kind}-ageing`} label={`${w.title} by ageing`} columns={columns(kind, props.query)} rows={ageing.rows}
            rowKey={(r) => String(r.party_id)} sortKey="balance" descending totalLabel="Total" />
        </section>
        <section className="card" aria-label="Outstanding bills" style={{ borderTopColor: lighter }}>
          <h2 className="card-title">Outstanding bills</h2>
          <ExplorerTable id={`${kind}-bills`} label="Outstanding bills" columns={billColumns(kind, props.query)} rows={ageing.bills}
            rowKey={(b) => `${b.party_id}|${b.bill}|${b.bill_date}`} sortKey="days" descending totalLabel="Total" />
        </section>
        {ageing.combined && <Typography.Text type="secondary">Several companies combined, without inter-company eliminations.</Typography.Text>}
      </>
    )
  }
  return (
    <ReportFrame {...props} title={kind === 'customers' ? 'Receivables' : 'Payables'} page={`${kind}-ageing`} period={undefined}
      combined={ageing?.combined ?? false} help={help(kind)}>
      {content}
    </ReportFrame>
  )
}
