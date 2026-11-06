// Receivables and payables with ageing (docs/design/dashboard.md Section 0.4; RPT-004): key
// cards (balance due, overdue, over 90 days, not covered by the stored bills), the outstanding
// bills by bucket as horizontal bars, and every customer (vendor) with its buckets and status in
// the table explorer, each name opening its page. As at the period's end. Figures:
// core/ageing.py (GET /api/v1/ageing/{kind}); formulas F-PTY-012 and F-PTY-013.

import { Alert, Skeleton, Typography } from 'antd'
import type { AgeingOut, AgeingRowOut, Company } from '../../api/types.ts'
import { HBars } from '../../components/HBars.tsx'
import { KeyCard } from '../../components/KeyCard.tsx'
import { StatusPill } from '../../components/StatusPill.tsx'
import { formatDate, formatExact, toScaled } from '../../format.ts'
import { fromScaled, type ExplorerColumn } from '../../reporting/explorer.ts'
import { ExplorerTable } from '../../reporting/ExplorerTable.tsx'
import { ReportFrame, type PanelProps } from '../../reporting/ReportFrame.tsx'
import { builtHref } from '../../shell/nav.ts'
import { tokens } from '../../theme.ts'
import { PARTY_WORDS, type PartyKind } from './words.ts'
import { partyPaymentStatusInfo } from '../../statuses.ts'

interface Props extends PanelProps {
  kind: PartyKind
  companies: Company[]
  ageing: AgeingOut | undefined
  loading: boolean
  error: Error | null
  dark: boolean
}

const BUCKET_LABELS: [keyof AgeingRowOut['buckets'], string][] = [
  ['not_due', 'Not due'],
  ['days_1_30', '1–30 days'],
  ['days_31_60', '31–60 days'],
  ['days_61_90', '61–90 days'],
  ['over_90', 'Over 90 days'],
]

function percentOf(part: string, whole: string): number | null {
  const all = toScaled(whole)
  return all > 0n ? Number((toScaled(part) * 1000n + all / 2n) / all) / 10 : null // rounded to one decimal
}

function columns(kind: PartyKind, query: PanelProps['query']): ExplorerColumn<AgeingRowOut>[] {
  const w = PARTY_WORDS[kind]
  return [
    { key: 'name', label: w.one, kind: 'text', value: (r) => r.name, link: (r) => builtHref([...w.group, String(r.party_id)], query) },
    { key: 'balance', label: w.balance, kind: 'amount', value: (r) => r.balance },
    ...BUCKET_LABELS.map(([key, label]): ExplorerColumn<AgeingRowOut> => ({ key, label, kind: 'amount', value: (r) => r.buckets[key] })),
    { key: 'uncovered', label: 'Not in bills', kind: 'amount', value: (r) => r.uncovered, hidden: true },
    {
      key: 'status',
      label: 'Status',
      kind: 'text',
      groupable: true,
      value: (r) => partyPaymentStatusInfo(r.payment_status ?? r.status, r.balance, kind).label,
      render: (r) => {
        const status = partyPaymentStatusInfo(r.payment_status ?? r.status, r.balance, kind)
        return <StatusPill text={status.label} tone={status.tone} help={status.meaning} />
      },
    },
    { key: 'meaning', label: 'Meaning', kind: 'text', value: (r) => partyPaymentStatusInfo(r.payment_status ?? r.status, r.balance, kind).meaning, wrap: true },
  ]
}

function help(kind: PartyKind) {
  const receivable = kind === 'customers'
  return (sourceName: string) => (
    <>
      <p>
        Every {receivable ? 'customer' : 'vendor'} with a balance or open bills at the period's end, known by name across the companies you chose.
        The <strong>buckets</strong> are the outstanding bills by days past their due date (the bill's own due date, else its date plus the
        credit period): not due, 1–30, 31–60, 61–90 and over 90 days (formula F-PTY-012).
      </p>
      <p>
        <strong>Not in bills</strong> is the balance the stored bills don't cover: bills from before the books' beginning (opening bills) aren't
        stored yet (F-PTY-013).
      </p>
      <p>
        <strong>To compare with {sourceName}:</strong> Display More Reports → Statements of Accounts → Outstandings →{' '}
        {receivable ? 'Receivables' : 'Payables'}, Ageing Analysis by due date, at the same date.
      </p>
    </>
  )
}

export function Ageing(props: Props) {
  const { kind, ageing } = props
  const w = PARTY_WORDS[kind]
  const colours = tokens[props.dark ? 'dark' : 'light']
  let content: React.ReactNode
  if (props.error) {
    content = <Alert type="error" showIcon message="The ageing couldn't be loaded." description={props.error.message} />
  } else if (props.loading || !ageing) {
    content = <Skeleton active paragraph={{ rows: 8 }} />
  } else {
    const t = ageing.total
    const billsText = fromScaled(toScaled(t.balance) - toScaled(t.uncovered))
    const asAt = `As at ${formatDate(ageing.as_of)}`
    const [green, charcoal, , grey] = colours.accents
    const bucketColours = [colours.primary, colours.neutralBar, colours.grossProfit, colours.negative, colours.negative]
    content = (
      <>
        <div className="sales-cards">
          <KeyCard label={w.balance} figure={{ value: t.balance }} note={asAt} accent={green} />
          <KeyCard label="Overdue" figure={{ value: t.overdue }} note={asAt} alert accent={charcoal} />
          <KeyCard label="Over 90 days" figure={{ value: t.buckets.over_90 }} note="Past their due date" alert accent={colours.negative} />
          <KeyCard label="Not in bills" figure={{ value: t.uncovered }} note="Opening bills aren't stored yet" accent={grey} />
        </div>
        <section className="card" aria-label="By days past due">
          <h2 className="card-title">Outstanding bills by days past due</h2>
          <HBars label="Outstanding bills by bucket"
            bars={BUCKET_LABELS.map(([key, label], i) => ({ label, amount: t.buckets[key], share: percentOf(t.buckets[key], billsText), colour: bucketColours[i] }))} />
          <p className="card-note">
            Bills total {formatExact(billsText)}; the balance due is {formatExact(t.balance)}.
          </p>
        </section>
        <section className="card" aria-label={`${w.title} by ageing`}>
          <ExplorerTable id={`${kind}-ageing`} label={`${w.title} by ageing`} columns={columns(kind, props.query)} rows={ageing.rows}
            rowKey={(r) => String(r.party_id)} sortKey="balance" descending totalLabel="Total" />
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
