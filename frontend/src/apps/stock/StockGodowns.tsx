// The Stock module's "By godown" view and the item page's breakdown (RPT-014; formulas
// F-STK-010 to F-STK-013): every item at each godown and batch at the period's end, in three
// sections counted as Tally counts them (core/stock_godowns.py, proved against Tally's Stock
// Summary and Godown Summary): our stock and others' stock held with us are in the total, which
// equals the Stock page and Tally's Stock Summary; our stock at job workers is shown apart,
// outside it. Each row opens the item's page at that godown. Figures: GET /api/v1/stock/godowns.

import { Typography } from 'antd'
import { useState } from 'react'
import type { Company, GodownRowOut, GodownSectionOut, StockGodownsOut } from '../../api/types.ts'
import { KeyCard } from '../../components/KeyCard.tsx'
import { ErrorState } from '../../components/loading/ErrorState.tsx'
import { Loading } from '../../components/loading/Loading.tsx'
import { Money } from '../../components/Money.tsx'
import { formatDate } from '../../format.ts'
import type { ExplorerColumn } from '../../reporting/explorer.ts'
import { ExplorerTable } from '../../reporting/ExplorerTable.tsx'
import { ReportFrame, type PanelProps } from '../../reporting/ReportFrame.tsx'
import type { Query } from '../../router.ts'
import { tokens } from '../../theme.ts'
import { DIVIDES_STOCK, godownHref, noteStartsOpen, NOT_SPLIT, rememberNote, SECTION_WORDS, type SectionKey } from './godownWords.ts'

function columns(query: Query, withItem: boolean): ExplorerColumn<GodownRowOut>[] {
  return [
    ...(withItem ? [{ key: 'item', label: 'Item', kind: 'text' as const, value: (r: GodownRowOut) => r.item, link: (r: GodownRowOut) => godownHref(r, query), groupable: true }] : []),
    { key: 'godown', label: 'Godown', kind: 'text', value: (r) => r.godown ?? NOT_SPLIT, link: (r) => godownHref(r, query), groupable: true },
    { key: 'batch', label: 'Batch', kind: 'text', value: (r) => r.batch, groupable: true },
    { key: 'unit', label: 'Unit', kind: 'text', value: (r) => r.unit, groupable: true, hidden: true },
    { key: 'quantity', label: 'Quantity', kind: 'count', value: (r) => r.quantity, formula: 'F-STK-010' },
    { key: 'value', label: 'Value', kind: 'amount', value: (r) => r.value ?? null, formula: 'F-STK-011' },
  ]
}

/** The sections, each with its total, its meaning and its rows. */
export function GodownSections({ sections, query, withItem, id }: { sections: GodownSectionOut[]; query: Query; withItem: boolean; id: string }) {
  if (sections.length === 0) return <Typography.Text type="secondary">No stock at the date.</Typography.Text>
  return (
    <>
      {sections.map((s) => {
        const words = SECTION_WORDS[s.key as SectionKey] ?? { title: s.key, help: '' }
        return (
          <section key={s.key} className="card godown-section" aria-label={words.title} data-figure="section" data-formula="F-STK-012">
            <div className="card-head">
              <h2 className="card-title">{words.title}</h2>
              <span className="card-small-note">
                {Number(s.quantity).toLocaleString('en-IN')} qty{s.value !== null && s.value !== undefined ? <> · <Money value={s.value} /></> : null}
                {' · '}
                <strong>{s.in_total ? 'In the total' : 'Not in the total'}</strong>
              </span>
            </div>
            <p className="card-note godown-help">{words.help}</p>
            <ExplorerTable id={`${id}-${s.key}`} label={words.title} columns={columns(query, withItem)} rows={s.rows}
              rowKey={(r) => `${r.item}|${r.godown ?? ''}|${r.batch ?? ''}`} totalLabel="Total" groupBy={withItem ? 'godown' : undefined} />
          </section>
        )
      })}
    </>
  )
}

/** "How this page divides stock": a small info box the reader can close; open the first
 *  time, then as they last left it (in this browser). */
export function DividesStockNote() {
  const [open] = useState(noteStartsOpen)
  return (
    <details className="card godown-note" open={open} onToggle={(e) => rememberNote(e.currentTarget.open)}>
      <summary className="godown-note-title">{DIVIDES_STOCK.title}</summary>
      <ul className="godown-note-points">
        {DIVIDES_STOCK.points.map((p) => (
          <li key={p.section}>
            <strong>{SECTION_WORDS[p.section].title}:</strong> {p.text}
          </li>
        ))}
      </ul>
      <p className="godown-note-footer">{DIVIDES_STOCK.footer}</p>
    </details>
  )
}

interface Props extends PanelProps {
  companies: Company[]
  found: StockGodownsOut | undefined
  loading: boolean
  error: Error | null
  onRetry?: () => void
  dark: boolean
}

function help(sourceName: string) {
  return (
    <>
      <p>
        Every item at each godown and batch at the end of the period: its opening by godown and batch plus every movement up to that day
        (formula F-STK-010). A row's value is its quantity at the item's rate (F-STK-011): {sourceName} keeps no value per item and godown, so
        the rows of an item add up to its value on the Stock page.
      </p>
      <p>
        <strong>The total</strong> is our stock plus others' stock held with us, as {sourceName}'s Stock Summary counts it (F-STK-013). Our stock
        at job workers is shown apart and isn't in it.
      </p>
      <p>
        <strong>To compare with {sourceName}:</strong> Gateway of Tally → Stock Summary (the total) and Godown Summary (each godown), at the same
        date.
      </p>
    </>
  )
}

export function StockGodowns(props: Props) {
  const { found } = props
  let content: React.ReactNode
  if (props.error) {
    content = <ErrorState message="The stock by godown couldn't be loaded." error={props.error} onRetry={props.onRetry} />
  } else if (props.loading || !found) {
    content = <Loading shape="dashboard" />
  } else {
    const [green, charcoal, lighter, grey] = tokens[props.dark ? 'dark' : 'light'].accents
    const section = (key: SectionKey) => found.sections.find((s) => s.key === key)
    const quantity = (key: SectionKey) => ({ value: section(key)?.quantity ?? '0' })
    const valueNote = found.value_on ? `Values at ${formatDate(found.value_on)}` : 'No stock values stored in the period yet'
    content = (
      <>
        <DividesStockNote />
        <div className="sales-cards">
          <KeyCard label="Stock in the total" formula="F-STK-013" figure={{ value: found.total_quantity }} unit="count" accent={green}
            note={`At ${formatDate(found.on)}; as Tally's Stock Summary`} />
          <KeyCard label="Value in the total" formula="F-STK-013" figure={{ value: found.total_value ?? null }} accent={charcoal} note={valueNote}
            missing="No stock values stored in the period yet" />
          <KeyCard label="Others' stock held with us" formula="F-STK-012" figure={quantity('held_for_others')} unit="count" accent={lighter}
            note="Not ours; in the total, as in Tally" />
          <KeyCard label="Our stock at job workers" formula="F-STK-012" figure={quantity('at_job_workers')} unit="count" accent={grey}
            note="Still ours; not in the total, as in Tally" />
        </div>
        <GodownSections sections={found.sections} query={props.query} withItem id="stock-godowns" />
        {found.godown_values.length > 0 && (
          <section className="card" aria-label="Tally's value by godown">
            <h2 className="card-title">{props.companies[0]?.health.source_name ?? 'Source'}'s own value by godown</h2>
            <ExplorerTable id="stock-godown-values" label="Value by godown" rows={found.godown_values} rowKey={(g) => g.name}
              columns={[
                { key: 'name', label: 'Godown', kind: 'text', value: (g) => g.name },
                { key: 'value', label: 'Value', kind: 'amount', value: (g) => g.value, formula: 'F-STK-005' },
              ]} note={valueNote} />
          </section>
        )}
      </>
    )
  }
  return (
    <ReportFrame {...props} title="Stock by godown" page="stock-godowns" period={found?.period} combined={found?.combined ?? false} help={help}>
      {content}
    </ReportFrame>
  )
}
