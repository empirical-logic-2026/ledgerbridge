// The Balance Sheet module (docs/design/dashboard.md Section 0.4; RPT-003, RPT-014): the stored
// Balance Sheet at the period's end beside the comparison period's, line by line with the
// change %, the totals of both sides, and the ratios as tiles (liquidity: current ratio, quick
// ratio, debt to equity; working capital: receivable, payable and inventory days and the
// working-capital days). Figures: core/balance_sheet.py (GET /api/v1/reports/balance-sheet);
// formulas F-BS-005, F-BS-006, F-RAT-001 to F-RAT-007.

import { Money } from '../../components/Money.tsx'
import { Alert, Typography } from 'antd'
import type { BalanceSheetReport, Company, RatioOut, SheetLineOut } from '../../api/types.ts'
import { Explained } from '../../components/Explained.tsx'
import { ErrorState } from '../../components/loading/ErrorState.tsx'
import { Loading } from '../../components/loading/Loading.tsx'
import { RatioTiles, type Tile } from '../../components/RatioTiles.tsx'
import { StatementChange, StatementTable, type StatementRow } from '../../components/StatementTable.tsx'
import { formatDate } from '../../format.ts'
import { ReportFrame, type PanelProps } from '../../reporting/ReportFrame.tsx'
import { againstOf } from '../../selection.ts'

interface Props extends PanelProps {
  companies: Company[]
  sheet: BalanceSheetReport | undefined
  loading: boolean
  error: Error | null
  onRetry?: () => void // ask again after an error
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

/** An amount as the Amounts setting shows it (components/Money.tsx). */
const Amount = Money

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
    <StatementTable
      label="Balance Sheet"
      compared={compared}
      columns={{
        label: 'Particulars',
        current: sheet.as_of ? formatDate(sheet.as_of) : 'Now',
        previous: sheet.before_as_of ? formatDate(sheet.before_as_of) : sheet.compared_with?.label,
        change: <Explained label="Change %">Change</Explained>,
      }}
      sections={SECTIONS.map(([section, title]) => {
        const total = sheet.totals.find((t) => t.section === section)
        const lines: StatementRow[] = sheet.lines
          .filter((line) => line.section === section)
          .map((line) => ({
            key: line.key,
            label: line.label,
            level: line.level,
            current: <Amount value={line.value} />,
            previous: <Amount value={line.before} />,
            change: <StatementChange change={line.change_pct} />,
          }))
        const totalRow: StatementRow = {
          key: `${section}-total`,
          label: `Total ${title.toLowerCase()}`,
          kind: 'total',
          current: <Amount value={total?.value} />,
          previous: <Amount value={total?.before} />,
          change: <StatementChange change={total?.change_pct} />,
        }
        return { key: section, title, rows: [...lines, totalRow] }
      })}
    />
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
    content = <ErrorState message="The Balance Sheet couldn't be loaded." error={props.error} onRetry={props.onRetry} />
  } else if (props.loading || !sheet) {
    content = <Loading shape="statement" />
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
    <ReportFrame
      {...props}
      title="Balance Sheet"
      page="balance-sheet"
      period={undefined}
      dateRange={sheet ? { start: sheet.period_start, end: sheet.period_end, balanceSheet: true } : undefined}
      combined={sheet?.combined ?? false}
      help={help}
    >
      {content}
    </ReportFrame>
  )
}
