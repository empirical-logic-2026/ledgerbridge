// The Transactions page (RPT-014; formula F-TRN-001): one row per ledger line of the companies
// and period chosen, in the table explorer: date, voucher type and number, the reference (e.g.
// the supplier's invoice number), the party, the line's ledger, the voucher's other ledgers
// (particulars), debit and credit, narration, the line's bills and cost centres, the order
// numbers (the orders the voucher is made against), the party's GSTIN, and the bank line's cheque
// number and UTR (only a value that looks like one), with its other bank details hidden. Rows: core/transactions.py (GET /api/v1/transactions).

import { Alert, Skeleton, Typography } from 'antd'
import type { Company, TransactionOut, TransactionsOut } from '../../api/types.ts'
import { formatMonth } from '../../format.ts'
import type { ExplorerColumn } from '../../reporting/explorer.ts'
import { ExplorerTable } from '../../reporting/ExplorerTable.tsx'
import { ReportFrame, type PanelProps } from '../../reporting/ReportFrame.tsx'
import type { Query } from '../../router.ts'
import { builtHref } from '../../shell/nav.ts'

interface Props extends PanelProps {
  companies: Company[] // the selected ones
  page: TransactionsOut | undefined
  loading: boolean
  error: Error | null
}

const UTR_SOURCES: Record<string, string> = {
  bank_field: "From the bank line's details",
  udf: 'From a user-defined field',
  narration: 'Found in the narration',
}

function columns(page: TransactionsOut, companies: Company[], query: Query): ExplorerColumn<TransactionOut>[] {
  const names = new Map(companies.map((c) => [c.id, c.name]))
  return [
    { key: 'month', label: 'Month', kind: 'text', value: (r) => formatMonth(r.date), groupable: true, hidden: true },
    { key: 'date', label: 'Date', kind: 'date', value: (r) => r.date },
    { key: 'type', label: 'Voucher Type', kind: 'text', value: (r) => r.voucher_type, groupable: true },
    { key: 'number', label: 'Voucher Number', kind: 'text', value: (r) => r.voucher_number, link: (r) => builtHref(['books', 'vouchers', String(r.voucher_id)], query) },
    { key: 'reference', label: 'Reference Number', kind: 'text', value: (r) => r.reference ?? null },
    { key: 'party', label: 'Party Name', kind: 'text', value: (r) => r.party ?? null, groupable: true, wrap: true },
    { key: 'ledger', label: 'Ledger Name', kind: 'text', value: (r) => r.ledger, groupable: true, wrap: true },
    {
      key: 'particulars',
      label: 'Particulars',
      kind: 'text',
      value: (r) => r.particulars ?? null,
      wrap: true,
      help: "The voucher's ledgers on the other side of this line (the bank for an expense paid, the expense for the bank), as the source's ledger report shows them.",
    },
    { key: 'debit', label: 'Debit', kind: 'amount', value: (r) => r.debit ?? null, help: "The line's amount when it is a debit (F-TRN-001)." },
    { key: 'credit', label: 'Credit', kind: 'amount', value: (r) => r.credit ?? null, help: "The line's amount when it is a credit, shown positive (F-TRN-001)." },
    { key: 'narration', label: 'Narration', kind: 'text', value: (r) => r.narration ?? null, wrap: true },
    { key: 'bills', label: 'Bill Number', kind: 'text', value: (r) => r.bills ?? null, help: "The bill references this line is allocated to (new or against a bill)." },
    { key: 'cost_centres', label: 'Cost Centre', kind: 'text', value: (r) => r.cost_centres ?? null, groupable: true, help: 'The cost centres this line is allocated to.' },
    { key: 'order', label: 'Order Number', kind: 'text', value: (r) => r.order_number ?? null, help: 'The sales or purchase orders the voucher is made against (PO / SO numbers): those the voucher names, else those its stock lines are against.' },
    { key: 'gstin', label: 'GSTIN', kind: 'text', value: (r) => r.gstin ?? null, help: "The party's GST identification number, from its ledger." },
    { key: 'cheque', label: 'Cheque Number', kind: 'text', value: (r) => r.cheque ?? null, help: "A bank line's cheque or instrument number." },
    {
      key: 'utr',
      label: 'UTR',
      kind: 'text',
      value: (r) => r.utr ?? null,
      render: (r) => (r.utr ? <span title={UTR_SOURCES[r.utr_source ?? ''] ?? ''}>{r.utr}</span> : <span className="muted">—</span>),
      help: "The bank's unique transaction reference: only a value that looks like one (NEFT/RTGS, IMPS/UPI, or written after \"UTR\"). Hover a value for where it was found.",
    },
    { key: 'transaction_type', label: 'Bank transaction type', kind: 'text', value: (r) => r.transaction_type ?? null, groupable: true, hidden: true, help: 'Cheque, e-Fund Transfer and so on, as the source records the bank line.' },
    { key: 'instrument_date', label: 'Instrument date', kind: 'date', value: (r) => r.instrument_date ?? null, hidden: true, help: "The cheque's or transfer's own date." },
    { key: 'bank_cleared_date', label: 'Bank cleared date', kind: 'date', value: (r) => r.bank_cleared_date ?? null, hidden: true, help: 'The date the bank cleared it (bank reconciliation); empty while not reconciled.' },
    { key: 'tally_bank_entry_id', label: 'Tally bank entry ID', kind: 'text', value: (r) => r.tally_bank_entry_id ?? null, hidden: true, help: "The source's own id for the bank entry (a code Tally generates): not a UTR." },
    { key: 'gst_registration', label: 'GST registration', kind: 'text', value: (r) => r.gst_registration ?? null, groupable: true, hidden: true, help: "The company's own GST registration (tax unit) the voucher is under." },
    { key: 'place_of_supply', label: 'Place of supply', kind: 'text', value: (r) => r.place_of_supply ?? null, groupable: true, hidden: true, help: 'The state of supply on the voucher (decides CGST + SGST or IGST).' },
    { key: 'party_gst_registration_type', label: 'Party GST type', kind: 'text', value: (r) => r.party_gst_registration_type ?? null, groupable: true, hidden: true, help: "The party's GST registration type: Regular, Composition, Unregistered and so on." },
    { key: 'gst_rates', label: 'GST rate', kind: 'text', value: (r) => r.gst_rates ?? null, hidden: true, help: "The line's own GST rates per duty head; empty when the line takes its rate from the item or ledger." },
    { key: 'irn', label: 'IRN', kind: 'text', value: (r) => r.irn ?? null, hidden: true, help: "The e-invoice's invoice reference number." },
    { key: 'irn_date', label: 'IRN date', kind: 'date', value: (r) => r.irn_date ?? null, hidden: true, help: 'The date the e-invoice was acknowledged.' },
    { key: 'eway_bill_number', label: 'E-way bill number', kind: 'text', value: (r) => r.eway_bill_number ?? null, hidden: true },
    { key: 'eway_bill_date', label: 'E-way bill date', kind: 'date', value: (r) => r.eway_bill_date ?? null, hidden: true },
    { key: 'company', label: 'Company', kind: 'text', value: (r) => names.get(r.company) ?? `Company ${r.company}`, groupable: true, hidden: !page.combined },
  ]
}

function help(sourceName: string) {
  return (
    <>
      <p>
        Every ledger line of the companies and period you chose, one row per line: a voucher with three ledgers has three rows. Only lines that count
        in the books (not cancelled, optional or deleted vouchers, and not orders or memorandum vouchers). <strong>Particulars</strong> are the
        voucher's ledgers on the other side of the line. A voucher's debits equal its credits.
      </p>
      <p>
        Group by voucher type, party, ledger, cost centre or month with Group by; choose columns with Columns; the CSV export has the exact amounts.
      </p>
      <p>
        <strong>To compare with {sourceName}:</strong> Display More Reports → Day Book for the same dates (detailed), or a ledger's Ledger Vouchers
        report.
      </p>
    </>
  )
}

export function Transactions(props: Props) {
  const { page } = props
  let content: React.ReactNode
  if (props.error) {
    content = <Alert type="error" showIcon message="The transactions couldn't be loaded." description={props.error.message} />
  } else if (props.loading || !page) {
    content = <Skeleton active paragraph={{ rows: 10 }} />
  } else {
    content = (
      <>
        {page.truncated && (
          <Alert type="warning" showIcon message={`Only the first ${page.rows.length.toLocaleString('en-IN')} lines are shown: choose a shorter period.`} />
        )}
        {page.rows.length === 0 ? (
          <Typography.Text type="secondary">No transactions in this period.</Typography.Text>
        ) : (
          <ExplorerTable id="transactions" label="Transactions" columns={columns(page, props.companies, props.query)} rows={page.rows}
            rowKey={(r) => String(r.line_id)} totalLabel="Total" />
        )}
      </>
    )
  }
  return (
    <ReportFrame {...props} title="Transactions" page="transactions" period={page?.period} combined={page?.combined ?? false} help={help}>
      {content}
    </ReportFrame>
  )
}
