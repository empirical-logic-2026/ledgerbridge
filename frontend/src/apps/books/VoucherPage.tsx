// The voucher page (Books › Voucher; RPT-007): one voucher as Tally holds it: its header (date,
// type, number, party, reference, narration), its ledger lines with debit and credit and the
// totals, its bill allocations and its stock lines. Opened from any voucher link (registers,
// transactions, stock, cost centres, party pages, outstanding bills). Read only; no UTR.
// Figures: core/vouchers.py (GET /api/v1/vouchers/{id}); formulas F-TRN-001, F-VCH-001,
// F-STK-008, F-STK-014, F-STK-015.

import { Alert, Descriptions, Typography } from 'antd'
import type { Company, VoucherBillOut, VoucherLineOut, VoucherOut, VoucherStockOut } from '../../api/types.ts'
import { ErrorState } from '../../components/loading/ErrorState.tsx'
import { Loading } from '../../components/loading/Loading.tsx'
import { Money } from '../../components/Money.tsx'
import { formatDate } from '../../format.ts'
import type { ExplorerColumn } from '../../reporting/explorer.ts'
import { ExplorerTable } from '../../reporting/ExplorerTable.tsx'
import { ReportFrame, type PanelProps } from '../../reporting/ReportFrame.tsx'
import type { Query } from '../../router.ts'
import { builtHref } from '../../shell/nav.ts'

interface Props extends PanelProps {
  companies: Company[]
  voucher: VoucherOut | undefined
  loading: boolean
  error: Error | null
  onRetry?: () => void
}

const BILL_TYPES: Record<string, string> = { new_ref: 'New Ref', against_ref: 'Agst Ref', advance: 'Advance', on_account: 'On Account' }

const LINE_COLUMNS: ExplorerColumn<VoucherLineOut>[] = [
  { key: 'ledger', label: 'Ledger', kind: 'text', value: (l) => l.ledger },
  { key: 'debit', label: 'Debit', kind: 'amount', value: (l) => l.debit ?? null, formula: 'F-TRN-001' },
  { key: 'credit', label: 'Credit', kind: 'amount', value: (l) => l.credit ?? null, formula: 'F-TRN-001' },
  { key: 'instrument', label: 'Cheque number', kind: 'text', value: (l) => l.instrument_number ?? null },
]

const BILL_COLUMNS: ExplorerColumn<VoucherBillOut>[] = [
  { key: 'ledger', label: 'Ledger', kind: 'text', value: (b) => b.ledger },
  { key: 'type', label: 'Type', kind: 'text', value: (b) => BILL_TYPES[b.bill_type] ?? b.bill_type },
  { key: 'name', label: 'Bill', kind: 'text', value: (b) => b.bill_name ?? null },
  { key: 'bill_date', label: 'Bill date', kind: 'date', value: (b) => b.bill_date ?? null },
  { key: 'due_date', label: 'Due date', kind: 'date', value: (b) => b.due_date ?? null },
  { key: 'debit', label: 'Debit', kind: 'amount', value: (b) => b.debit ?? null, formula: 'F-TRN-001' },
  { key: 'credit', label: 'Credit', kind: 'amount', value: (b) => b.credit ?? null, formula: 'F-TRN-001' },
]

function stockColumns(query: Query): ExplorerColumn<VoucherStockOut>[] {
  return [
    { key: 'item', label: 'Item', kind: 'text', value: (s) => s.item, link: (s) => builtHref(['stock', 'summary', String(s.item_id)], query) },
    { key: 'godown', label: 'Godown', kind: 'text', value: (s) => s.godown ?? null },
    { key: 'other_godown', label: 'Other godown', kind: 'text', value: (s) => s.other_godown ?? null },
    { key: 'batch', label: 'Batch', kind: 'text', value: (s) => s.batch ?? null },
    { key: 'quantity', label: 'Quantity', kind: 'count', value: (s) => s.quantity, formula: 'F-STK-014' },
    { key: 'rate', label: 'Rate', kind: 'amount', value: (s) => s.rate ?? null, summed: false, formula: 'F-STK-015' },
    { key: 'amount', label: 'Amount', kind: 'amount', value: (s) => s.amount, formula: 'F-STK-008' },
  ]
}

function help(sourceName: string) {
  return (
    <>
      <p>
        One voucher as {sourceName} holds it: its ledger lines (debits and credits are equal: formula F-VCH-001), the bills it raises or settles and
        the stock it moves. A cancelled voucher has no lines; an optional one doesn't post to the books.
      </p>
      <p>
        <strong>To compare with {sourceName}:</strong> Display More Reports → Day Book at the voucher's date, and open the voucher.
      </p>
    </>
  )
}

export function VoucherPage(props: Props) {
  const { voucher: v } = props
  let content: React.ReactNode
  if (props.error) {
    content = <ErrorState message="The voucher couldn't be loaded." error={props.error} onRetry={props.onRetry} />
  } else if (props.loading || !v) {
    content = <Loading shape="report" />
  } else {
    const company = props.companies.find((c) => c.id === v.company)
    content = (
      <>
        {(v.cancelled || v.optional) && (
          <Alert type="info" showIcon message={v.cancelled ? 'This voucher is cancelled: it has no lines and changes nothing.' : 'This voucher is optional: it does not post to the books.'} />
        )}
        <section className="card" aria-label="Voucher">
          <Descriptions size="small" column={{ xs: 1, sm: 2, lg: 3 }}
            items={[
              { key: 'date', label: 'Date', children: formatDate(v.date) },
              { key: 'type', label: 'Voucher type', children: v.voucher_type },
              { key: 'number', label: 'Voucher number', children: v.number },
              { key: 'party', label: 'Party', children: v.party ?? '—' },
              { key: 'reference', label: 'Reference', children: v.reference ?? '—' },
              { key: 'company', label: 'Company', children: company?.display_name ?? company?.name ?? `Company ${v.company}` },
            ]} />
          {v.narration && <Typography.Paragraph className="voucher-narration">{v.narration}</Typography.Paragraph>}
          <p className="card-small-note" data-figure="totals" data-formula="F-VCH-001">
            Total debit <Money value={v.total_debit} /> · total credit <Money value={v.total_credit} />
          </p>
        </section>
        <section className="card" aria-label="Ledger lines">
          <h2 className="card-title">Ledger lines</h2>
          <ExplorerTable id="voucher-lines" label="Ledger lines" columns={LINE_COLUMNS} rows={v.lines} rowKey={(l) => String(l.line_no)} totalLabel="Total" />
        </section>
        {v.bills.length > 0 && (
          <section className="card" aria-label="Bills">
            <h2 className="card-title">Bills</h2>
            <ExplorerTable id="voucher-bills" label="Bills" columns={BILL_COLUMNS} rows={v.bills} rowKey={(b) => `${b.ledger}|${b.bill_type}|${b.bill_name ?? ''}`} />
          </section>
        )}
        {v.stock.length > 0 && (
          <section className="card" aria-label="Stock">
            <h2 className="card-title">Stock</h2>
            <ExplorerTable id="voucher-stock" label="Stock" columns={stockColumns(props.query)} rows={v.stock} rowKey={(s) => String(s.line_no)} totalLabel="Total" />
          </section>
        )}
      </>
    )
  }
  return (
    <ReportFrame {...props} title={v ? `${v.voucher_type} ${v.number}` : 'Voucher'} page="voucher" period={undefined} combined={false} help={help}>
      {content}
    </ReportFrame>
  )
}
