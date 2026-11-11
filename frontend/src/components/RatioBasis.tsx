// What a ratio is worked out from (F-RAT-008 to F-RAT-010; parts F-BS-007 to F-BS-011), shown
// on the ratio tile's hover so anyone can check it against the Balance Sheet: current assets
// and current liabilities with their parts (or borrowings and equity), the ledgers marked as
// short-term, and whether several companies are added up without inter-company eliminations.

import type { RatioBasisOut, RatioPartOut } from '../api/types.ts'
import { formatAmount, useAmountFormat } from '../amountFormat.ts'
import { formatDate, toScaled } from '../format.ts'
import { fromScaled } from '../reporting/explorer.ts'

export type BasisKind = 'current_ratio' | 'quick_ratio' | 'debt_to_equity'

function Parts({ title, total, parts }: { title: string; total: string | null; parts: RatioPartOut[] }) {
  const { format } = useAmountFormat()
  return (
    <div className="ratio-basis-side">
      <div className="ratio-basis-row ratio-basis-total">
        <span>{title}</span>
        <span>{total === null ? '—' : formatAmount(total, format)}</span>
      </div>
      {parts.map((p) => (
        <div key={p.key} className="ratio-basis-row" data-formula="F-BS-010">
          <span>{p.label}</span>
          <span>{formatAmount(p.amount, format)}</span>
        </div>
      ))}
    </div>
  )
}

export function RatioBasis({ kind, basis, asOf }: { kind: BasisKind; basis: RatioBasisOut; asOf: string | null }) {
  const { format } = useAmountFormat()
  const stock = kind === 'quick_ratio' ? [{ key: 'less_stock', label: 'Less: closing stock', amount: basis.stock }] : []
  return (
    <div className="ratio-basis" aria-label="How it is worked out">
      {kind === 'debt_to_equity' ? (
        <>
          <Parts title="Borrowings" total={basis.borrowings} parts={basis.borrowing_parts} />
          <Parts title="÷ Equity (capital and profit)" total={basis.equity} parts={[]} />
        </>
      ) : (
        <>
          <Parts title="Current assets" total={basis.current_assets} parts={[...basis.asset_parts, ...stock]} />
          <Parts title="÷ Current liabilities" total={basis.current_liabilities} parts={basis.liability_parts} />
        </>
      )}
      {kind === 'quick_ratio' && (
        <p className="ratio-basis-note">
          Quick assets: {formatAmount(fromScaled(toScaled(basis.current_assets) - toScaled(basis.stock)), format)} (current assets less closing stock).
        </p>
      )}
      {basis.marked_short_term > 0 && (
        <p className="ratio-basis-note">
          Includes {basis.marked_short_term} ledger{basis.marked_short_term === 1 ? '' : 's'} marked as short-term.
        </p>
      )}
      <p className="ratio-basis-note">
        Each ledger on its own side by its balance (Schedule III).{asOf ? ` At ${formatDate(asOf)}.` : ''}
        {basis.combined ? ' Several companies combined, without inter-company eliminations.' : ''}
      </p>
    </div>
  )
}
