// The P&L & KPIs module's figures above the statement (docs/design/dashboard.md Section 0.4):
// the margin tiles (gross margin, net margin, cost of sales and other costs as % of net sales,
// each with its change in points), the expense structure (each cost line of the Profit & Loss
// as % of net sales, as horizontal bars), the monthly trend (net sales with gross and net
// profit marked) and the goal tracker's placeholder. Figures: GET /api/v1/home and the
// statement report; formulas F-PL-005, F-PL-006, F-PL-008 and F-PL-010.

import type { Home, StatementReport } from '../../api/types.ts'
import { EChart } from '../../components/EChart.tsx'
import { GoalPlaceholder } from '../../components/GoalPlaceholder.tsx'
import { HBars } from '../../components/HBars.tsx'
import { RatioTiles } from '../../components/RatioTiles.tsx'
import { toScaled } from '../../format.ts'
import { againstOf } from '../../selection.ts'
import { tokens } from '../../theme.ts'
import { profitTrend } from './homeChart.ts'

interface Props {
  home: Home | undefined
  report: StatementReport | undefined
  dark: boolean
}

export function PnlKpis({ home, report, dark }: Props) {
  if (!home) return null
  const pl = home.profit_loss
  const colours = tokens[dark ? 'dark' : 'light']
  const missing = pl.reason ? `Needs the stored statements: ${pl.reason}.` : undefined
  const costs = (report?.lines ?? [])
    .filter((line) => line.level === 'main' && !line.higher_is_better && line.values.total && toScaled(line.values.total) > 0n)
    .sort((a, b) => Number(b.pct_of_sales.total ?? 0) - Number(a.pct_of_sales.total ?? 0))
  return (
    <div className="pnl-kpis">
      <section className="card" aria-label="Margins">
        <h2 className="card-title">Margins</h2>
        <RatioTiles
          label="Margins as % of net sales"
          against={againstOf(home.compared_with)}
          tiles={[
            { label: 'Gross margin', value: pl.gross_margin_pct.value, change: pl.gross_margin_pct.change_pts, unit: 'percent', higherIsBetter: true, missing },
            { label: 'Net margin', value: pl.net_profit_pct.value, change: pl.net_profit_pct.change_pts, unit: 'percent', higherIsBetter: true, missing },
            { label: 'Cost of sales', value: pl.cost_of_sales_pct.value, change: pl.cost_of_sales_pct.change_pts, unit: 'percent', higherIsBetter: false, missing, note: '% of net sales' },
            { label: 'Other costs', value: pl.other_costs_pct.value, change: pl.other_costs_pct.change_pts, unit: 'percent', higherIsBetter: false, missing, note: 'Indirect expenses less incomes, % of net sales' },
          ]}
        />
      </section>
      <section className="card" aria-label="Expense structure">
        <h2 className="card-title">Expense structure (% of net sales)</h2>
        {costs.length ? (
          <HBars label="Cost lines as % of net sales"
            bars={costs.map((line, i) => ({
              label: line.label,
              amount: line.values.total ?? '0',
              share: line.pct_of_sales.total === null || line.pct_of_sales.total === undefined ? null : Number(line.pct_of_sales.total),
              colour: i === 0 ? colours.primary : colours.neutralBar,
            }))} />
        ) : (
          <p className="card-note">No cost lines for this period{pl.reason ? `: ${pl.reason}` : ''}.</p>
        )}
      </section>
      <section className="card pnl-trend" aria-label="Monthly trend">
        <h2 className="card-title">Net sales and profit by month (₹ lakh)</h2>
        <EChart key={dark ? 'dark' : 'light'} option={profitTrend(home, colours)} dark={dark} height={240} />
      </section>
      <GoalPlaceholder goals={['net sales', 'gross margin', 'net margin']} />
    </div>
  )
}
