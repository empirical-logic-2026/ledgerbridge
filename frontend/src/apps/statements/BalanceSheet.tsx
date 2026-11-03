// The Balance Sheet module (docs/design/dashboard.md Section 0.4; RPT-003, RPT-014): the stored
// Balance Sheet at the period's end beside the comparison period's, line by line with the
// change %, the totals of both sides, and the ratios as tiles (liquidity: current ratio, quick
// ratio, debt to equity; working capital: receivable, payable and inventory days and the
// working-capital days). Figures: core/balance_sheet.py (GET /api/v1/reports/balance-sheet);
// formulas F-BS-005, F-BS-006, F-RAT-001 to F-RAT-007.

import { Alert, Skeleton, Tooltip, Typography } from 'antd'
import type { BalanceSheetReport, Company, RatioOut, SheetLineOut } from '../../api/types.ts'
import { Explained } from '../../components/Explained.tsx'
import { RatioTiles, type Tile } from '../../components/RatioTiles.tsx'
import { formatChange, formatCompact, formatDate, formatExact, toScaled } from '../../format.ts'
import { ReportFrame, type PanelProps } from '../../reporting/ReportFrame.tsx'
import { againstOf } from '../../selection.ts'

interface Props extends PanelProps {
  companies: Company[]
  sheet: BalanceSheetReport | undefined
  loading: boolean
  error: Error | null
}

const SECTIONS: [SheetLineOut['section'], string][] = [
  ['assets', 'Assets'],
  ['liabilities', 'Liabilities and capital'],
]
const HIGHER_IS_BETTER: Record<string, boolean> = {
  current_ratio: true,
  quick_ratio: true,
  debt_to_equity: false,
  receivable_days: false,
  payable_days: true,
  inventory_days: false,
  working_capital_days: false,
}

function Amount({ value }: { value: string | null | undefined }) {
  if (value === null || value === undefined) return <span>—</span>
  return (
    <Tooltip title={formatExact(value)}>
      <span className={toScaled(value) < 0n ? 'negative' : undefined}>{formatCompact(value)}</span>
    </Tooltip>
  )
}

function Change({ pct }: { pct: string | null | undefined }) {
  return pct ? <span className="muted">{formatChange(pct)}</span> : <span className="muted">—</span>
}

function tile(r: RatioOut): Tile {
  return {
    label: r.label,
    value: r.value ?? null,
    unit: r.unit,
    change: r.change,
    higherIsBetter: HIGHER_IS_BETTER[r.key] ?? true,
    note: r.formula_id,
    missing: 'Its divisor is zero, or a statement or the stock value is missing for this date.',
  }
}

function Statement({ sheet }: { sheet: BalanceSheetReport }) {
  const compared = sheet.compared_with !== null && sheet.compared_with !== undefined
  return (
    <table className="report-table" aria-label="Balance Sheet">
      <thead>
        <tr>
          <th>Particulars</th>
          <th className="num">{sheet.as_of ? formatDate(sheet.as_of) : 'Now'}</th>
          {compared && <th className="num">{sheet.before_as_of ? formatDate(sheet.before_as_of) : sheet.compared_with?.label}</th>}
          {compared && <th className="num"><Explained label="Change %">Change</Explained></th>}
        </tr>
      </thead>
      {SECTIONS.map(([section, title]) => {
        const total = sheet.totals.find((t) => t.section === section)
        return (
          <tbody key={section}>
            <tr className="line-section">
              <th scope="rowgroup" colSpan={compared ? 4 : 2}>{title}</th>
            </tr>
            {sheet.lines
              .filter((line) => line.section === section)
              .map((line) => (
                <tr key={line.key} className={`line-${line.level}`}>
                  <th scope="row">{line.label}</th>
                  <td className="num">
                    <Amount value={line.value} />
                  </td>
                  {compared && (
                    <td className="num">
                      <Amount value={line.before} />
                    </td>
                  )}
                  {compared && (
                    <td className="num">
                      <Change pct={line.change_pct} />
                    </td>
                  )}
                </tr>
              ))}
            <tr className="line-total">
              <th scope="row">Total {title.toLowerCase()}</th>
              <td className="num">
                <Amount value={total?.value} />
              </td>
              {compared && (
                <td className="num">
                  <Amount value={total?.before} />
                </td>
              )}
              {compared && (
                <td className="num">
                  <Change pct={total?.change_pct} />
                </td>
              )}
            </tr>
          </tbody>
        )
      })}
    </table>
  )
}

function help(sourceName: string) {
  return (
    <>
      <p>
        The Balance Sheet at the period's end (or the last statement stored in it), beside the end of the period it is compared with: our own,
        built from the books and checked line by line against {sourceName}'s (formula F-BS-005).
      </p>
      <p>
        <strong>Ratios:</strong> current ratio = current assets ÷ current liabilities; quick ratio leaves out the closing stock; debt to equity =
        Loans (Liability) ÷ (Capital Account + Profit &amp; Loss A/c); receivable, payable and inventory days = receivables ÷ net sales, payables ÷
        net purchases, closing stock ÷ cost of sales, times the period's days (F-RAT-001 to F-RAT-007).
      </p>
      <p>
        <strong>To compare with {sourceName}:</strong> Gateway of Tally → Balance Sheet at the same date; Display More Reports → Ratio Analysis.
      </p>
    </>
  )
}

export function BalanceSheet(props: Props) {
  const { sheet } = props
  let content: React.ReactNode
  if (props.error) {
    content = <Alert type="error" showIcon message="The Balance Sheet couldn't be loaded." description={props.error.message} />
  } else if (props.loading || !sheet) {
    content = <Skeleton active paragraph={{ rows: 10 }} />
  } else if (sheet.reason) {
    content = <Alert type="info" showIcon message="No Balance Sheet for this period." description={`${sheet.reason}.`} />
  } else {
    const ratios = new Map(sheet.ratios.map((r) => [r.key, r]))
    const pick = (keys: string[]) => keys.map((k) => ratios.get(k)).filter((r): r is RatioOut => r !== undefined).map(tile)
    const against = againstOf(sheet.compared_with)
    content = (
      <div className="sheet-layout">
        <section className="card" aria-label="The Balance Sheet">
          <Statement sheet={sheet} />
          {sheet.before_reason && <p className="card-note">No comparison: {sheet.before_reason}.</p>}
          {sheet.combined && <Typography.Text type="secondary">Several companies combined, without inter-company eliminations.</Typography.Text>}
        </section>
        <div className="sheet-ratios">
          <section className="card" aria-label="Liquidity">
            <h2 className="card-title">Liquidity and leverage</h2>
            <RatioTiles label="Liquidity ratios" against={against} tiles={pick(['current_ratio', 'quick_ratio', 'debt_to_equity', 'working_capital_days'])} />
          </section>
          <section className="card" aria-label="Working capital">
            <h2 className="card-title">Working capital</h2>
            <RatioTiles label="Working capital days" against={against} tiles={pick(['receivable_days', 'payable_days', 'inventory_days'])} />
          </section>
        </div>
      </div>
    )
  }
  return (
    <ReportFrame {...props} title="Balance Sheet" page="balance-sheet" period={undefined} combined={sheet?.combined ?? false} help={help}>
      {content}
    </ReportFrame>
  )
}
