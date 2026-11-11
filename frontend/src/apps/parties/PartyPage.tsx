// A customer's or vendor's page (docs/design/dashboard.md Section 0.3, screen 8): the header
// with where the party sits and its key facts; key figures (balance due, overdue, net sales
// against the comparison period, average days to pay); tabs with the invoices and credit notes, receipts
// (payments), the ledger statement with the running balance, the outstanding bills and the
// monthly trend, each in the table explorer. Figures: core/parties.py
// (GET /api/v1/parties/{kind}/{id}).

import { Alert, Button, Tabs, Typography } from 'antd'
import { ErrorState } from '../../components/loading/ErrorState.tsx'
import { Loading } from '../../components/loading/Loading.tsx'
import type { EChartsOption } from 'echarts'
import type { BillOut, Company, EntryOut, PartyInvoiceOut, PartyMonthOut, PartyOut, SettlementOut } from '../../api/types.ts'
import { EChart } from '../../components/EChart.tsx'
import { KeyCard } from '../../components/KeyCard.tsx'
import { againstOf } from '../../selection.ts'
import { formatDate, formatExact, formatMonth, toLakhs, toScaled } from '../../format.ts'
import type { ExplorerColumn } from '../../reporting/explorer.ts'
import { ExplorerTable } from '../../reporting/ExplorerTable.tsx'
import { WhatIsThis } from '../../reporting/WhatIsThis.tsx'
import type { Query } from '../../router.ts'
import { builtHref } from '../../shell/nav.ts'
import { tokens, type Tokens } from '../../theme.ts'
import { PARTY_WORDS, type PartyKind } from './words.ts'
import { companyDisplayName } from '../../companyDisplayName.ts'
import { paymentStatusInfo } from '../../statuses.ts'
import { StatusPill } from '../../components/StatusPill.tsx'

export type PartyTab = 'invoices' | 'settlements' | 'statement' | 'bills' | 'monthly'

interface Props {
  kind: PartyKind
  companies: Company[] // the selected ones
  party: PartyOut | undefined
  loading: boolean
  error: Error | null
  onRetry?: () => void // ask again after an error
  dark: boolean
  tab: PartyTab
  onTab: (tab: PartyTab) => void
  query: Query
}

/** "₹1,20,000.00 Dr" / "Cr": a balance as the source's ledger shows it. */
function drCr(value: string): string {
  const scaled = toScaled(value)
  if (scaled === 0n) return formatExact('0')
  return `${formatExact(value.replace(/^-/, ''))} ${scaled > 0n ? 'Dr' : 'Cr'}`
}

function voucherLink(id: number, query: Query) {
  return builtHref(['books', 'vouchers', String(id)], query)
}

function InvoiceStatus({ invoice, kind }: { invoice: PartyInvoiceOut; kind: PartyKind }) {
  const status = paymentStatusInfo(invoice.payment_status ?? invoice.status, kind)
  const timing =
    invoice.status === 'overdue'
      ? ` (${invoice.days} days)`
      : invoice.status === 'due'
        ? ` (${invoice.days === 0 ? 'due today' : `due in ${invoice.days} days`})`
        : ''
  return <StatusPill text={`${status.label}${timing}`} tone={status.tone} help={status.meaning} />
}

function invoiceColumns(kind: PartyKind, names: Map<number, string>, combined: boolean, query: Query): ExplorerColumn<PartyInvoiceOut>[] {
  return [
    { key: 'date', label: 'Date', kind: 'date', value: (i) => i.date },
    { key: 'type', label: 'Vch Type', kind: 'text', value: (i) => i.voucher_type, groupable: true },
    { key: 'number', label: 'Vch No.', kind: 'text', value: (i) => i.number, link: (i) => voucherLink(i.voucher_id, query) },
    { key: 'company', label: 'Company', kind: 'text', value: (i) => names.get(i.company) ?? `Company ${i.company}`, groupable: true, hidden: !combined },
    {
      key: 'amount',
      label: 'Amount',
      kind: 'amount',
      value: (i) => (i.debit !== null ? i.debit : i.credit !== null ? `-${i.credit}` : null),
    },
    { key: 'value', label: 'Before taxes', kind: 'amount', value: (i) => i.side_value, hidden: true },
    {
      key: 'status',
      label: 'Status',
      kind: 'text',
      value: (i) => paymentStatusInfo(i.payment_status ?? i.status, kind).label,
      render: (i) => <InvoiceStatus invoice={i} kind={kind} />,
      groupable: true,
    },
    { key: 'meaning', label: 'Meaning', kind: 'text', value: (i) => paymentStatusInfo(i.payment_status ?? i.status, kind).meaning, wrap: true },
    { key: 'narration', label: 'Narration', kind: 'text', value: (i) => i.narration, hidden: true },
  ]
}

function settlementColumns(kind: PartyKind, names: Map<number, string>, combined: boolean, query: Query): ExplorerColumn<SettlementOut>[] {
  return [
    { key: 'date', label: 'Date', kind: 'date', value: (s) => s.date },
    { key: 'type', label: 'Vch Type', kind: 'text', value: (s) => s.voucher_type, groupable: true },
    { key: 'number', label: 'Vch No.', kind: 'text', value: (s) => s.number, link: (s) => voucherLink(s.voucher_id, query) },
    { key: 'company', label: 'Company', kind: 'text', value: (s) => names.get(s.company) ?? `Company ${s.company}`, groupable: true, hidden: !combined },
    { key: 'amount', label: kind === 'customers' ? 'Received' : 'Paid', kind: 'amount', value: (s) => s.amount },
    { key: 'narration', label: 'Narration', kind: 'text', value: (s) => s.narration },
  ]
}

function statementColumns(names: Map<number, string>, combined: boolean, query: Query): ExplorerColumn<EntryOut>[] {
  return [
    { key: 'month', label: 'Month', kind: 'text', value: (e) => formatMonth(e.date), groupable: true, hidden: true },
    { key: 'date', label: 'Date', kind: 'date', value: (e) => e.date },
    { key: 'particulars', label: 'Particulars', kind: 'text', value: (e) => e.particulars },
    { key: 'type', label: 'Vch Type', kind: 'text', value: (e) => e.voucher_type, groupable: true },
    { key: 'number', label: 'Vch No.', kind: 'text', value: (e) => e.number, link: (e) => voucherLink(e.voucher_id, query) },
    { key: 'debit', label: 'Debit', kind: 'amount', value: (e) => e.debit },
    { key: 'credit', label: 'Credit', kind: 'amount', value: (e) => e.credit },
    { key: 'balance', label: 'Balance', kind: 'amount', value: (e) => e.balance, render: (e) => drCr(e.balance), summed: false },
    { key: 'company', label: 'Company', kind: 'text', value: (e) => names.get(e.company) ?? `Company ${e.company}`, groupable: true, hidden: !combined },
    { key: 'narration', label: 'Narration', kind: 'text', value: (e) => e.narration, hidden: true },
  ]
}

function billStatusInfo(bill: BillOut, kind: PartyKind) {
  if (bill.payment_status !== undefined && bill.payment_status !== null) {
    return paymentStatusInfo(bill.payment_status, kind)
  }
  const amount = toScaled(bill.amount)
  if (amount <= -50n) return paymentStatusInfo('advance', kind)
  if (amount < 50n) return paymentStatusInfo('settled', kind)
  return paymentStatusInfo(bill.overdue_days > 0 ? 'overdue' : 'pending', kind)
}

function billColumns(kind: PartyKind, names: Map<number, string>, combined: boolean): ExplorerColumn<BillOut>[] {
  return [
    { key: 'name', label: 'Bill', kind: 'text', value: (b) => b.name },
    { key: 'date', label: 'Bill date', kind: 'date', value: (b) => b.date },
    { key: 'due', label: 'Due', kind: 'date', value: (b) => b.due },
    { key: 'amount', label: 'Pending', kind: 'amount', value: (b) => b.amount },
    {
      key: 'status',
      label: 'Status',
      kind: 'text',
      value: (b) => billStatusInfo(b, kind).label,
      render: (b) => {
        const status = billStatusInfo(b, kind)
        return <StatusPill text={status.label} tone={status.tone} help={status.meaning} />
      },
      groupable: true,
    },
    { key: 'meaning', label: 'Meaning', kind: 'text', value: (b) => billStatusInfo(b, kind).meaning, wrap: true },
    {
      key: 'overdue',
      label: 'Overdue by',
      kind: 'count',
      value: (b) => b.overdue_days,
      render: (b) => (b.overdue_days > 0 && toScaled(b.amount) > 0n ? <span className="negative">{b.overdue_days} days</span> : '—'),
      summed: false,
    },
    { key: 'company', label: 'Company', kind: 'text', value: (b) => names.get(b.company) ?? `Company ${b.company}`, groupable: true, hidden: !combined },
  ]
}

function monthColumns(kind: PartyKind): ExplorerColumn<PartyMonthOut>[] {
  const w = PARTY_WORDS[kind]
  return [
    { key: 'month', label: 'Month', kind: 'text', value: (m) => formatMonth(m.month) },
    { key: 'net', label: w.net, kind: 'amount', value: (m) => m.net },
    { key: 'invoices', label: 'Invoices', kind: 'count', value: (m) => m.invoices },
    { key: 'settled', label: w.settled, kind: 'amount', value: (m) => m.settled },
  ]
}

function trend(kind: PartyKind, months: PartyMonthOut[], colours: Tokens): EChartsOption {
  const w = PARTY_WORDS[kind]
  return {
    backgroundColor: 'transparent',
    grid: { left: 48, right: 12, top: 28, bottom: 28 },
    legend: { top: 0, right: 0, textStyle: { color: colours.muted }, data: [w.net, w.settled] },
    tooltip: {
      trigger: 'axis',
      formatter: (params: unknown) => {
        const [first] = params as { dataIndex: number }[]
        const m = months[first.dataIndex]
        return `${formatMonth(m.month)}<br/>${w.net} ${formatExact(m.net)}<br/>${w.settled} ${formatExact(m.settled)}`
      },
    },
    xAxis: { type: 'category', data: months.map((m) => formatMonth(m.month).slice(0, 3)), axisLabel: { color: colours.muted } },
    yAxis: { type: 'value', axisLabel: { color: colours.muted }, splitLine: { lineStyle: { color: colours.border } } },
    series: [
      { type: 'bar', name: w.net, data: months.map((m) => toLakhs(m.net)), itemStyle: { color: colours.primary } },
      { type: 'line', name: w.settled, data: months.map((m) => toLakhs(m.settled)), itemStyle: { color: colours.text }, lineStyle: { color: colours.text } },
    ],
  }
}

function Help({ kind, sourceName }: { kind: PartyKind; sourceName: string }) {
  const w = PARTY_WORDS[kind]
  return (
    <>
      <p>
        One {w.one.toLowerCase()}, by name across the companies you chose. The <strong>{w.balance.toLowerCase()}</strong> is their ledgers' balance
        at the period's end; <strong>overdue</strong> is what their outstanding bills past the due date add up to (due on the bill's due date, else its
        date plus the credit period). <strong>Average days to pay</strong> weighs each settlement in the period by its amount, from the bill's date.
      </p>
      <p>
        <strong>Where the figures come from:</strong> the books, rebuilt after every sync; the balances are validated against {sourceName}'s. Bills
        include the opening bills (from before the books' beginning); where an amount isn't split into bills (on account), the bills cover less
        than the balance: the page then says so.
      </p>
      <p>
        <strong>To compare with {sourceName}:</strong> the ledger statement is the party's Ledger Vouchers for the same dates; the outstanding bills
        its Bills Receivable (Payable) or the party's Outstandings on the period's last day.
      </p>
    </>
  )
}

export function PartyPage(props: Props) {
  const { kind, party, companies, query } = props
  const w = PARTY_WORDS[kind]
  const sourceName = companies[0]?.health.source_name ?? 'the source'
  const names = new Map(companies.map((c) => [c.id, companyDisplayName(c)]))
  const colours = tokens[props.dark ? 'dark' : 'light']

  let content: React.ReactNode
  if (props.error) {
    content = <ErrorState message={`The ${w.one.toLowerCase()} couldn't be loaded.`} error={props.error} onRetry={props.onRetry} />
  } else if (props.loading || !party) {
    content = <Loading shape="dashboard" />
  } else {
    const combined = party.companies.length > 1
    const asAt = `as at ${formatDate(party.period.end)}`
    const overdueBills = party.bills.filter((b) => b.overdue_days > 0 && toScaled(b.amount) > 0n).length
    const facts = [
      party.main_channel ? `Main channel: ${party.main_channel}` : null,
      `Companies: ${party.companies.map((c) => names.get(c) ?? `Company ${c}`).join(', ')}`,
      party.credit_days ? `Credit period ${party.credit_days} days` : null,
    ].filter(Boolean)
    const uncovered = toScaled(party.bills_cover) !== toScaled(party.balance)
    content = (
      <>
        <section className="card party-head" aria-label={`${w.one} details`}>
          <div>
            <span className="party-path">{[w.one, ...party.group_path].join(' · ')}</span>
            <Typography.Title level={2} className="report-title">
              {party.name}
            </Typography.Title>
            <span className="party-facts">{facts.join(' · ')}</span>
          </div>
          <div className="party-actions">
            <Button onClick={() => props.onTab('statement')}>Ledger statement</Button>
            <Button onClick={() => props.onTab('bills')}>Outstanding bills</Button>
            <WhatIsThis><Help kind={kind} sourceName={sourceName} /></WhatIsThis>
          </div>
        </section>
        <div className="sales-cards">
          <KeyCard label={w.balance} figure={{ value: party.balance }} note={asAt} tone="up-neutral" accent={colours.accents[0]} />
          <KeyCard label="Overdue" figure={{ value: party.overdue }} alert note={`${overdueBills} bill${overdueBills === 1 ? '' : 's'} past the due date`} tone="up-neutral"
            accent={colours.accents[1]} />
          <KeyCard label={w.net} figure={party.net} against={againstOf(party.compared_with)} note={`${Number(party.invoices.value ?? 0).toLocaleString('en-IN')} invoices`}
            accent={colours.accents[2]} spark={party.monthly.map((m) => toLakhs(m.net))} />
          <KeyCard
            label="Average days to pay"
            figure={{ value: party.days_to_pay }}
            unit="days"
            accent={colours.accents[3]}
            missing={`No bill was settled in this period.`}
            note={party.credit_days ? `credit period ${party.credit_days} days` : `${w.settled.toLowerCase()} against bills`}
          />
        </div>
        <section className="card" aria-label={`${w.one} lists`}>
          <Tabs
            activeKey={props.tab}
            onChange={(key) => props.onTab(key as PartyTab)}
            items={[
              {
                key: 'invoices',
                label: kind === 'customers' ? 'Invoices and credit notes' : 'Invoices and debit notes',
                children: (
                  <ExplorerTable id={`${kind}-invoices`} label="Invoices" columns={invoiceColumns(kind, names, combined, query)} rows={party.invoices_list}
                    rowKey={(i) => String(i.voucher_id)} sortKey="date" descending totalLabel="Total" />
                ),
              },
              {
                key: 'settlements',
                label: w.settled,
                children: (
                  <ExplorerTable id={`${kind}-settlements`} label={w.settled} columns={settlementColumns(kind, names, combined, query)} rows={party.settlements}
                    rowKey={(s) => String(s.voucher_id)} sortKey="date" descending totalLabel="Total" />
                ),
              },
              {
                key: 'statement',
                label: 'Ledger statement',
                children: (
                  <>
                    <p className="report-note">Opening balance on {formatDate(party.period.start)}: {drCr(party.statement_opening)}</p>
                    {party.statement_truncated && <Alert type="warning" showIcon message="Only the first 20,000 entries are shown: choose fewer months." />}
                    <ExplorerTable id={`${kind}-statement`} label="Ledger statement" columns={statementColumns(names, combined, query)} rows={party.statement}
                      rowKey={(e) => String(e.voucher_id)} pageSize={500} totalLabel="Total" />
                  </>
                ),
              },
              {
                key: 'bills',
                label: 'Outstanding bills',
                children: (
                  <>
                    {uncovered && (
                      <p className="report-note">
                        The bills add up to {formatExact(party.bills_cover)} of the {formatExact(party.balance)} {w.balance.toLowerCase()}: bills from before
                        the books' beginning and amounts not allocated to bills aren't listed.
                      </p>
                    )}
                    <ExplorerTable id={`${kind}-bills`} label="Outstanding bills" columns={billColumns(kind, names, combined)} rows={party.bills}
                      rowKey={(b) => `${b.company}-${b.name}-${b.date}`} sortKey="due" totalLabel="Total" />
                  </>
                ),
              },
              {
                key: 'monthly',
                label: 'Monthly trend',
                children: (
                  <>
                    <EChart key={props.dark ? 'dark' : 'light'} option={trend(kind, party.monthly, colours)} dark={props.dark} height={240} />
                    <ExplorerTable id={`${kind}-monthly`} label="Monthly trend" columns={monthColumns(kind)} rows={party.monthly} rowKey={(m) => m.month} totalLabel="Total" />
                  </>
                ),
              },
            ]}
          />
        </section>
      </>
    )
  }

  return (
    <div className="report-page">
      <div className="report-main">{content}</div>
    </div>
  )
}
