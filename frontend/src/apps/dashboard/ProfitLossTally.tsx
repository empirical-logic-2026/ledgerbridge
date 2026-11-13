// The Profit & Loss in Tally's layout (ADR-056; the P&L page's default view): TallyPrime's
// Profit & Loss A/c with its two sides. The header names the companies and the period; the
// left side holds Opening Stock, the debit groups and Gross Profit c/o, then Gross Loss b/f,
// the debit groups of the net block and Nett Profit; the right side the credit groups,
// Closing Stock and Gross Loss c/o, then Gross Profit b/f, the credit groups and Nett Loss.
// The gross block's subtotals and the Totals line up and are equal. A group opens its
// sub-groups and ledgers (each opening its Ledger statement); the stock opens the Stock
// summary. Figures: core/profit_loss_tally.py (GET /api/v1/reports/profit-loss/tally);
// formulas F-PL-011 to F-PL-017.

import { Alert, Button, Segmented, Typography } from 'antd'
import { useState } from 'react'
import type { Company, TallyBlockOut, TallyColumnOut, TallyDrillOut, TallyProfitLossOut, TallyRowOut, TallySideOut } from '../../api/types.ts'
import { AccountTree } from '../../components/AccountTree.tsx'
import { openable, type TreeRow } from '../../components/accountTree.ts'
import { ErrorState } from '../../components/loading/ErrorState.tsx'
import { Loading } from '../../components/loading/Loading.tsx'
import { Money } from '../../components/Money.tsx'
import { companyDisplayName } from '../../companyDisplayName.ts'
import { formatDate } from '../../format.ts'
import { href, type Query } from '../../router.ts'
import { builtHref, ledgerHref } from '../../shell/nav.ts'
import { COMBINED_NOTE } from './words.ts'
import { PL_TALLY_WORDS as W } from './notes.ts'

export type Side = 'left' | 'right'

interface Props {
  companies: Company[]
  report: TallyProfitLossOut | undefined
  loading: boolean
  error: Error | null
  onRetry?: () => void
  query: Query
  onEnd: (day: string) => void // choose a stored date as the period's end
  line?: string // the group drilled into
  side: Side
  drill: { found: TallyDrillOut | undefined; loading: boolean; error: Error | null; onRetry?: () => void }
}

const FORMULA: Record<TallyRowOut['kind'], string> = {
  group: 'F-PL-011',
  stock: 'F-PL-017',
  gross_carried: 'F-PL-012',
  gross_brought: 'F-PL-012',
  net_result: 'F-PL-014',
}

/** The page with a line drilled into (or none). */
function lineHref(query: Query, line?: string, side?: Side): string {
  return href(['pnl', 'profit-loss'], { ...query, line, side })
}

function Amounts({ values, columns }: { values: Record<string, string | null | undefined>; columns: TallyColumnOut[] }) {
  return (
    <>
      {columns.map((c) => (
        <td key={c.key} className="num">
          {values[c.key] ? <Money value={values[c.key] as string} /> : null}
        </td>
      ))}
    </>
  )
}

function label(row: TallyRowOut, side: Side, query: Query) {
  if (row.kind === 'group' && row.group) return <a href={lineHref(query, row.group, side)}>{row.label}</a>
  if (row.kind === 'stock') return <a href={builtHref(['stock', 'summary'], query)}>{row.label}</a>
  return row.label
}

/** One side of one block, padded with empty rows so both sides' subtotals line up. */
function BlockRows({ side, name, rows, columns, query }: { side: TallySideOut; name: Side; rows: number; columns: TallyColumnOut[]; query: Query }) {
  const padding = Array.from({ length: Math.max(0, rows - side.rows.length) })
  return (
    <>
      {side.rows.map((row) => (
        <tr key={row.key} className={`tally-${row.kind}`} data-figure="line" data-formula={FORMULA[row.kind]}>
          <th scope="row">{label(row, name, query)}</th>
          <Amounts values={row.values} columns={columns} />
        </tr>
      ))}
      {padding.map((_, n) => (
        <tr key={`pad-${n}`} className="tally-pad" aria-hidden="true">
          <th />
          {columns.map((c) => <td key={c.key} />)}
        </tr>
      ))}
    </>
  )
}

function SideTable({ report, name, gross, net, query }: { report: TallyProfitLossOut; name: Side; gross: TallyBlockOut; net: TallyBlockOut; query: Query }) {
  // One company: one amount column, as Tally; several: one each and the total.
  const several = report.columns.length > 2
  const columns = several ? report.columns : report.columns.filter((c) => c.key === 'total')
  const mine = (block: TallyBlockOut) => (name === 'left' ? block.left : block.right)
  const total = (side: TallySideOut, text: string, formula: string) => (
    <tr className="line-total" data-figure="line" data-formula={formula}>
      <th scope="row">{text}</th>
      <Amounts values={side.total} columns={columns} />
    </tr>
  )
  return (
    <table className="report-table tally-side" aria-label={name === 'left' ? W.left : W.right}>
      <thead>
        <tr>
          <th scope="col">Particulars</th>
          {columns.map((c) => (
            <th key={c.key} scope="col" className="num">
              {several ? c.label : `${formatDate(report.start ?? report.period_start)} to ${formatDate(report.end ?? report.period_end)}`}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        <BlockRows side={mine(gross)} name={name} rows={Math.max(gross.left.rows.length, gross.right.rows.length)} columns={columns} query={query} />
        {total(mine(gross), '', 'F-PL-013')}
        <BlockRows side={mine(net)} name={name} rows={Math.max(net.left.rows.length, net.right.rows.length)} columns={columns} query={query} />
        {total(mine(net), 'Total', 'F-PL-013')}
      </tbody>
    </table>
  )
}

function Drill({ line, side, drill, query }: { line: string; side: Side; drill: Props['drill']; query: Query }) {
  const [open, setOpen] = useState<Set<string> | undefined>(undefined)
  const found = drill.found
  let body: React.ReactNode
  if (drill.error) {
    body = <ErrorState message="The line's groups and ledgers couldn't be loaded." error={drill.error} onRetry={drill.onRetry} />
  } else if (drill.loading || !found) {
    body = <Loading shape="report" />
  } else if (found.reason || found.rows.length === 0) {
    body = <Alert type="info" showIcon message={`${found.reason ?? 'Nothing to show'}.`} />
  } else {
    const rows: TreeRow[] = found.rows.map((r) => ({
      key: r.key, label: r.label, kind: r.kind, depth: r.depth, parent: r.parent ?? null, formula: 'F-PL-016',
      cells: [<Money key="a" value={r.amount} />], to: ledgerHref(r.ledger_id, query),
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
        <AccountTree label={`${found.rows[0].label} by group and ledger`} columns={[{ label: 'Particulars' }, { label: side === 'left' ? 'Debit' : 'Credit' }]}
          rows={rows} open={shown} onToggle={toggle} />
        <p className="card-note">
          <a href="#" onClick={(e) => { e.preventDefault(); setOpen(openable(rows)) }}>{W.openAll}</a> · {W.drillNote}
        </p>
      </>
    )
  }
  return (
    <section className="card" aria-label="Drill-down">
      <div className="card-head">
        <h2 className="card-title">{found?.rows[0]?.label ?? line}</h2>
        <a href={lineHref(query)}>Close</a>
      </div>
      {body}
    </section>
  )
}

export function ProfitLossTally(props: Props) {
  const { report } = props
  if (props.error) return <ErrorState message="The Profit & Loss couldn't be loaded." error={props.error} onRetry={props.onRetry} />
  if (props.loading || !report) return <Loading shape="report" />
  if (!report.gross || !report.net || !report.end) {
    return (
      <Alert
        type="info"
        showIcon
        message={W.noEnd}
        description={
          <>
            <p>{report.reason ? `${report.reason[0].toUpperCase()}${report.reason.slice(1)}.` : ''}</p>
            {report.nearest.length > 0 && (
              <p>
                {W.nearest}{' '}
                {report.nearest.map((day) => (
                  <Button key={day} size="small" onClick={() => props.onEnd(day)} className="nearest-date">
                    {W.endOn(formatDate(day))}
                  </Button>
                ))}
              </p>
            )}
          </>
        }
      />
    )
  }
  const names = props.companies.map(companyDisplayName).join(' + ')
  return (
    <>
      {props.line && <Drill key={`${props.line}-${props.side}`} line={props.line} side={props.side} drill={props.drill} query={props.query} />}
      <section className="card" aria-label="Profit & Loss A/c">
        <div className="tally-head">
          <Typography.Text strong>{names}</Typography.Text>
          <Typography.Text>Profit &amp; Loss A/c</Typography.Text>
          <Typography.Text type="secondary">
            {formatDate(report.start ?? report.period_start)} to {formatDate(report.end)}
          </Typography.Text>
          {report.combined && <Typography.Text type="secondary">{COMBINED_NOTE}</Typography.Text>}
        </div>
        <div className="tally-sides report-table-wrap">
          <SideTable report={report} name="left" gross={report.gross} net={report.net} query={props.query} />
          <SideTable report={report} name="right" gross={report.gross} net={report.net} query={props.query} />
        </div>
        <p className="card-note">{W.how}</p>
      </section>
    </>
  )
}

/** The P&L page's two views: Tally's layout (the default) or the Analysis view. */
export function PlViewSwitch({ analysis, onAnalysis }: { analysis: boolean; onAnalysis: (analysis: boolean) => void }) {
  return (
    <div className="pl-view-switch">
      <Segmented
        aria-label="Profit & Loss view"
        value={analysis ? 'analysis' : 'tally'}
        onChange={(v) => onAnalysis(v === 'analysis')}
        options={[
          { value: 'tally', label: W.tally },
          { value: 'analysis', label: W.analysis },
        ]}
      />
    </div>
  )
}
