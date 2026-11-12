// The Balance Sheet module (docs/design/dashboard.md Section 0.4; RPT-003, RPT-014): the stored
// Balance Sheet at the period's end beside the comparison period's, line by line with the
// change %, the totals of both sides, and the ratios as tiles (liquidity: current ratio, quick
// ratio, debt to equity; working capital: receivable, payable and inventory days and the
// working-capital days). Figures: core/balance_sheet.py (GET /api/v1/reports/balance-sheet);
// formulas F-BS-005, F-BS-006, F-RAT-004 to F-RAT-010 (hover: their parts, F-BS-007 to F-BS-011).
// A line's label opens its drill-down (ADR-055): its groups and ledgers at the date, each level
// adding up to the line (F-BS-012; GET /api/v1/reports/balance-sheet/drill), a ledger opening
// its Ledger statement.

import { Money } from '../../components/Money.tsx'
import { Alert, Typography } from 'antd'
import { useState } from 'react'
import type { BalanceSheetReport, Company, DrillOut, RatioOut, SheetLineOut } from '../../api/types.ts'
import { AccountTree } from '../../components/AccountTree.tsx'
import { openable, type TreeRow } from '../../components/accountTree.ts'
import { Explained } from '../../components/Explained.tsx'
import { ErrorState } from '../../components/loading/ErrorState.tsx'
import { Loading } from '../../components/loading/Loading.tsx'
import { RatioBasis, type BasisKind } from '../../components/RatioBasis.tsx'
import { RatioTiles, type Tile } from '../../components/RatioTiles.tsx'
import { StatementChange, StatementTable, type StatementRow } from '../../components/StatementTable.tsx'
import { formatDate } from '../../format.ts'
import { ReportFrame, type PanelProps } from '../../reporting/ReportFrame.tsx'
import { href, type Query } from '../../router.ts'
import { againstOf } from '../../selection.ts'
import { builtHref, ledgerHref } from '../../shell/nav.ts'
import { DRILL_WORDS } from './notes.ts'

interface Props extends PanelProps {
  companies: Company[]
  sheet: BalanceSheetReport | undefined
  loading: boolean
  error: Error | null
  onRetry?: () => void // ask again after an error
  line?: string // the line drilled into ("assets:current assets")
  drill?: { found: DrillOut | undefined; loading: boolean; error: Error | null; onRetry?: () => void }
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

function isBasisKind(key: string): key is BasisKind {
  return key === 'current_ratio' || key === 'quick_ratio' || key === 'debt_to_equity'
}

function tile(r: RatioOut, asOf: string | null): Tile {
  return {
    label: r.label,
    value: r.value ?? null,
    unit: r.unit,
    change: r.change,
    higherIsBetter: HIGHER_IS_BETTER[r.key] ?? true,
    note: r.formula_id,
    formula: r.formula_id,
    missing: 'Its divisor is zero, or a statement or the stock value is missing for this date.',
    basis: r.basis && isBasisKind(r.key) ? <RatioBasis kind={r.key} basis={r.basis} asOf={asOf} /> : undefined,
  }
}

/** The page with a line drilled into (or none: `line` undefined). */
function drillHref(query: Query, line?: string): string {
  return href(['balance-sheet', 'statement'], { ...query, line })
}

function Statement({ sheet, query }: { sheet: BalanceSheetReport; query: Query }) {
  const compared = sheet.compared_with !== null && sheet.compared_with !== undefined
  return (
    <StatementTable
      label="Balance Sheet"
      formula="F-BS-005"
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
            to: line.level === 'main' && line.value && Number(line.value) !== 0 && !/forex/i.test(line.label) ? drillHref(query, line.key) : undefined,
          }))
        const totalRow: StatementRow = {
          key: `${section}-total`,
          label: `Total ${title.toLowerCase()}`,
          kind: 'total',
          formula: 'F-BS-006',
          current: <Amount value={total?.value} />,
          previous: <Amount value={total?.before} />,
          change: <StatementChange change={total?.change_pct} />,
        }
        return { key: section, title, rows: [...lines, totalRow] }
      })}
    />
  )
}

function Drill({ line, drill, query }: { line: string; drill: NonNullable<Props['drill']>; query: Query }) {
  const found = drill.found
  const [open, setOpen] = useState<Set<string> | undefined>(undefined)
  let body: React.ReactNode
  if (drill.error) {
    body = <ErrorState message="The line's groups and ledgers couldn't be loaded." error={drill.error} onRetry={drill.onRetry} />
  } else if (drill.loading || !found) {
    body = <Loading shape="report" />
  } else if (found.reason) {
    body = <Alert type="info" showIcon message={`${found.reason}.`} />
  } else {
    const rows: TreeRow[] = found.rows.map((r) => ({
      key: r.key, label: r.label, kind: r.kind, depth: r.depth, parent: r.parent ?? null, formula: 'F-BS-012',
      cells: [<Amount key="a" value={r.amount} />],
      to: r.kind === 'stock' ? builtHref(['stock', 'summary'], query) : ledgerHref(r.ledger_id, query),
    }))  // prettier-ignore
    const shown = open ?? new Set(rows.filter((r) => r.depth === 0).map((r) => r.key))
    const toggle = (key: string) => {
      const next = new Set(shown)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      setOpen(next)
    }
    body = (
      <>
        <AccountTree label={`${found.line} by group and ledger`} columns={[{ label: 'Particulars' }, { label: <Explained label="Amount" help={DRILL_WORDS.help} /> }]}
          rows={rows} open={shown} onToggle={toggle} />
        <p className="card-note">
          <a href="#" onClick={(e) => { e.preventDefault(); setOpen(openable(rows)) }}>Open every group</a>
          {found.rows.some((r) => r.label.startsWith('Forex revaluation difference')) ? ` · ${DRILL_WORDS.revaluation}` : ''}
        </p>
      </>
    )
  }
  const title = found?.as_of ? DRILL_WORDS.title(found.line, formatDate(found.as_of)) : line
  return (
    <section className="card" aria-label="Drill-down">
      <div className="card-head">
        <h2 className="card-title">{title}</h2>
        <a href={drillHref(query)}>{DRILL_WORDS.close}</a>
      </div>
      {body}
    </section>
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
        <strong>Ratios:</strong> current assets and current liabilities as Schedule III shows them: each ledger on the side its balance is on
        (a debtor in credit is a liability, a creditor in debit an asset), Bank OD A/c, banks in credit and loans marked short-term as
        short-term borrowings, the closing stock once (F-BS-007, F-BS-008). Current ratio = current assets ÷ current liabilities (F-RAT-008);
        quick ratio leaves out the closing stock (F-RAT-009); debt to equity = borrowings ÷ (Capital Account + Profit &amp; Loss A/c)
        (F-RAT-010). Hover a ratio to see its parts. Receivable, payable and inventory days = receivables ÷ net sales, payables ÷ net
        purchases, closing stock ÷ cost of sales, times the period's days (F-RAT-004 to F-RAT-007).
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
    const pick = (keys: string[]) => keys.map((k) => ratios.get(k)).filter((r): r is RatioOut => r !== undefined).map((r) => tile(r, sheet.as_of ?? null))
    const against = againstOf(sheet.compared_with)
    content = (
      <>
      {props.line && props.drill && <Drill key={props.line} line={props.line} drill={props.drill} query={props.query} />}
      <div className="sheet-layout">
        <section className="card" aria-label="The Balance Sheet">
          <Statement sheet={sheet} query={props.query} />
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
      </>
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
