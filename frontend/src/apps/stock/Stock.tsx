// The Stock module (RPT-014; formulas F-STK-001 to F-STK-008): the stock summary (key cards,
// the stock value at the last stored dates, the value by stock group and by godown, and every
// item with its opening, inward, outward and closing quantity, value and rate) and one item's
// page (its movements with the quantity after each and the other godown of a move, its months,
// and where it is by godown and batch; at one godown with `?godown=`). Quantities are ours,
// proven against the source item by item; values are the source's own, at the last stored
// date within the period. Figures: core/stock.py (GET /api/v1/stock and .../{id}).

import { Alert, Tabs, Typography } from 'antd'
import { ErrorState } from '../../components/loading/ErrorState.tsx'
import { Loading } from '../../components/loading/Loading.tsx'
import type { EChartsOption } from 'echarts'
import type { Company, StockItemMonthOut, StockItemOut, StockItemPageOut, StockMovementOut, StockNamedValue, StockOut } from '../../api/types.ts'
import { EChart } from '../../components/EChart.tsx'
import { HBars } from '../../components/HBars.tsx'
import { KeyCard } from '../../components/KeyCard.tsx'
import { formatDate, formatExact, formatMonth, toLakhs, toScaled } from '../../format.ts'
import type { ExplorerColumn } from '../../reporting/explorer.ts'
import { ExplorerTable } from '../../reporting/ExplorerTable.tsx'
import { ReportFrame, type PanelProps } from '../../reporting/ReportFrame.tsx'
import type { Query } from '../../router.ts'
import { builtHref } from '../../shell/nav.ts'
import { GodownSections } from './StockGodowns.tsx'
import { tokens, type Tokens } from '../../theme.ts'

interface SummaryProps extends PanelProps {
  companies: Company[] // the selected ones
  stock: StockOut | undefined
  loading: boolean
  error: Error | null
  onRetry?: () => void // ask again after an error
  dark: boolean
}

interface ItemProps extends PanelProps {
  companies: Company[]
  page: StockItemPageOut | undefined
  loading: boolean
  error: Error | null
  onRetry?: () => void // ask again after an error
  dark: boolean
}

function itemHref(id: number, query: Query): string | undefined {
  return builtHref(['stock', 'summary', String(id)], query)
}

function companyNames(companies: Company[], ids: number[]): string {
  const names = new Map(companies.map((c) => [c.id, c.name]))
  return ids.map((c) => names.get(c) ?? `Company ${c}`).join(', ')
}

/** "On 31-Aug-2026, the last stored date in the period", or why there is no value. */
function valueNote(on: string | null): string {
  return on ? `At ${formatDate(on)}, the last stored date in the period` : 'No stock values stored in the period yet'
}

function itemColumns(stock: StockOut, companies: Company[], query: Query): ExplorerColumn<StockItemOut>[] {
  return [
    { key: 'name', label: 'Item', kind: 'text', value: (i) => i.name, link: (i) => itemHref(i.item_id, query) },
    { key: 'group', label: 'Stock group', kind: 'text', value: (i) => i.group, groupable: true },
    { key: 'unit', label: 'Unit', kind: 'text', value: (i) => i.unit, groupable: true },
    { key: 'opening', label: 'Opening qty', kind: 'count', value: (i) => i.opening, summed: false },
    { key: 'inward', label: 'Inward qty', kind: 'count', value: (i) => i.inward, summed: false },
    { key: 'outward', label: 'Outward qty', kind: 'count', value: (i) => i.outward, summed: false },
    { key: 'closing', label: 'Closing qty', kind: 'count', value: (i) => i.closing, summed: false },
    { key: 'rate', label: 'Rate', kind: 'amount', value: (i) => i.rate, summed: false },
    { key: 'value', label: 'Value', kind: 'amount', value: (i) => i.value },
    { key: 'companies', label: 'Companies', kind: 'text', value: (i) => companyNames(companies, i.companies), groupable: true, hidden: !stock.combined },
  ]
}

function bars(parts: StockNamedValue[], total: string | null, colour: string) {
  const whole = total ? toScaled(total) : 0n
  return parts.map((p) => ({
    label: p.name,
    amount: p.value,
    share: whole > 0n ? Number((toScaled(p.value) * 10000n) / whole) / 100 : null,
    colour,
  }))
}

function valueChart(stock: StockOut, colours: Tokens): EChartsOption {
  return {
    backgroundColor: 'transparent',
    grid: { left: 48, right: 8, top: 16, bottom: 28 },
    tooltip: {
      trigger: 'axis',
      formatter: (params: unknown) => {
        const d = stock.by_date[(params as { dataIndex: number }[])[0].dataIndex]
        return `${formatDate(d.date)}<br/>Stock value ${formatExact(d.value)}`
      },
    },
    xAxis: { type: 'category', data: stock.by_date.map((d) => formatDate(d.date).slice(3)), axisLabel: { color: colours.muted } },
    yAxis: { type: 'value', axisLabel: { color: colours.muted }, splitLine: { lineStyle: { color: colours.border } } },
    series: [{ type: 'bar', name: 'Stock value', data: stock.by_date.map((d) => toLakhs(d.value)), itemStyle: { color: colours.primary } }],
  }
}

function help(sourceName: string) {
  return (
    <>
      <p>
        Every stock item of the companies you chose, by name: the same item in several companies is one row. The <strong>quantities</strong> are
        worked out from the books: the item's opening plus the stock movements of vouchers that aren't cancelled, optional or deleted, of types that
        move stock, leaving out goods at a job worker (they are still {sourceName}'s stock with a third party). Each validation proves the closing
        quantity of every item against {sourceName}'s own.
      </p>
      <p>
        The <strong>values</strong> are {sourceName}'s own (its valuation method), stored at its statement dates: shown at the last stored date within
        the period. The rate is the value divided by the closing quantity. Quantities of different units are not added together.
      </p>
      <p>
        <strong>To compare with {sourceName}:</strong> Gateway of Tally → Stock Summary for the same period (closing quantity, rate and value); by
        location: Godown Summary.
      </p>
    </>
  )
}

export function StockSummary(props: SummaryProps) {
  const { stock } = props
  const colours = tokens[props.dark ? 'dark' : 'light']
  let content: React.ReactNode
  if (props.error) {
    content = <ErrorState message="The stock couldn't be loaded." error={props.error} onRetry={props.onRetry} />
  } else if (props.loading || !stock) {
    content = <Loading shape="dashboard" />
  } else if (stock.items.length === 0) {
    content = <Alert type="info" showIcon message="No stock items in the companies you chose." />
  } else {
    const [green, charcoal, lighter] = colours.accents
    const negative = stock.items.filter((i) => toScaled(i.closing) < 0n).length
    content = (
      <>
        <div className="sales-cards">
          <KeyCard label="Stock value" figure={{ value: stock.total_value ?? null }} note={valueNote(stock.value_on)} accent={green}
            spark={stock.by_date.map((d) => toLakhs(d.value))}
            missing="Run ./dev.ps1 statements to store the source's stock values" />
          <KeyCard label="Stock items" formula="F-STK-009" figure={{ value: String(stock.items.length) }} unit="count" accent={charcoal} />
          <KeyCard label="Items with negative stock" figure={{ value: String(negative) }} unit="count" alert accent={lighter}
            note="More went out than came in: check with the source" />
        </div>
        <div className="home-charts">
          <section className="card" aria-label="Stock value by date">
            <h2 className="card-title">Stock value at the stored dates (₹ lakh)</h2>
            {stock.by_date.length ? (
              <EChart key={props.dark ? 'dark' : 'light'} option={valueChart(stock, colours)} dark={props.dark} height={260} />
            ) : (
              <Typography.Text type="secondary">No stock values stored up to the period's end.</Typography.Text>
            )}
          </section>
          <section className="card" aria-label="Stock value by group and godown">
            <h2 className="card-title">By stock group</h2>
            {stock.by_group.length ? <HBars formula="F-STK-005" label="Stock value by stock group" bars={bars(stock.by_group, stock.total_value ?? null, colours.primary)} />
              : <Typography.Text type="secondary">No values by stock group.</Typography.Text>}
            <h2 className="card-title">By godown</h2>
            {stock.by_godown.length ? <HBars formula="F-STK-005" label="Stock value by godown" bars={bars(stock.by_godown, stock.total_value ?? null, colours.neutralBar)} />
              : <Typography.Text type="secondary">No values by godown.</Typography.Text>}
          </section>
        </div>
        <section className="card" aria-label="Stock items">
          <ExplorerTable id="stock-items" label="Stock items" columns={itemColumns(stock, props.companies, props.query)} rows={stock.items}
            rowKey={(i) => String(i.item_id)} totalLabel="Total" note={valueNote(stock.value_on)} />
        </section>
      </>
    )
  }
  return (
    <ReportFrame {...props} title="Stock summary" page="stock-summary" period={stock?.period} combined={stock?.combined ?? false} help={help}>
      {content}
    </ReportFrame>
  )
}

type Movement = StockMovementOut & { row: number } // its place in the list (a voucher can move an item twice)

function movementColumns(page: StockItemPageOut, companies: Company[], query: Query): ExplorerColumn<Movement>[] {
  return [
    { key: 'month', label: 'Month', kind: 'text', value: (m) => formatMonth(m.date), groupable: true, hidden: true },
    { key: 'date', label: 'Date', kind: 'date', value: (m) => m.date },
    { key: 'type', label: 'Vch Type', kind: 'text', value: (m) => m.voucher_type, groupable: true },
    { key: 'number', label: 'Vch No.', kind: 'text', value: (m) => m.voucher_number, link: (m) => builtHref(['books', 'vouchers', String(m.voucher_id)], query) },
    { key: 'godown', label: 'Godown', kind: 'text', value: (m) => m.godown, groupable: true },
    { key: 'other_godown', label: 'Other godown', kind: 'text', value: (m) => m.other_godown ?? null, groupable: true,
      help: 'Where the stock went (a line going out) or came from (a line coming in), for a move between godowns.' },
    { key: 'quantity', label: 'Quantity', kind: 'count', value: (m) => m.quantity, summed: false },
    { key: 'balance', label: 'Balance qty', kind: 'count', value: (m) => m.balance, summed: false },
    { key: 'amount', label: 'Voucher value', kind: 'amount', value: (m) => m.amount },
    { key: 'company', label: 'Company', kind: 'text', value: (m) => companyNames(companies, [m.company]), groupable: true, hidden: page.item.companies.length < 2 },
  ]
}

const MONTH_COLUMNS: ExplorerColumn<StockItemMonthOut>[] = [
  { key: 'month', label: 'Month', kind: 'text', value: (m) => formatMonth(m.month) },
  { key: 'inward', label: 'Inward qty', kind: 'count', value: (m) => m.inward, summed: false },
  { key: 'outward', label: 'Outward qty', kind: 'count', value: (m) => m.outward, summed: false },
  { key: 'closing', label: 'Closing qty', kind: 'count', value: (m) => m.closing, summed: false },
  { key: 'value', label: 'Value', kind: 'amount', value: (m) => m.value, summed: false },
]

export function StockItemPage(props: ItemProps) {
  const { page } = props
  let content: React.ReactNode
  if (props.error) {
    content = <ErrorState message="The stock item couldn't be loaded." error={props.error} onRetry={props.onRetry} />
  } else if (props.loading || !page) {
    content = <Loading shape="dashboard" />
  } else {
    const item = page.item
    const [green, charcoal, lighter] = tokens[props.dark ? 'dark' : 'light'].accents
    const unit = item.unit ? ` ${item.unit}` : ''
    content = (
      <>
        <Typography.Paragraph className="muted">{[item.group && `Stock group: ${item.group}`, item.unit && `Unit: ${item.unit}`].filter(Boolean).join(' · ')}</Typography.Paragraph>
        <div className="sales-cards">
          <KeyCard label="Closing quantity" figure={{ value: item.closing }} unit="count" alert={toScaled(item.closing) < 0n} note={`Opening ${Number(item.opening).toLocaleString('en-IN')}${unit}`}
            accent={green} spark={page.months.map((m) => Number(m.closing))} />
          <KeyCard label="Value" figure={{ value: item.value ?? null }} note={valueNote(page.value_on)} missing="No value stored for this item at that date" accent={charcoal}
            spark={page.months.map((m) => (m.value === null ? null : toLakhs(m.value)))} />
          <KeyCard label="Rate" figure={{ value: item.rate ?? null }} note={`Per${unit || ' unit'}`} missing="No value, or no quantity" accent={lighter} />
        </div>
        {page.godown && (
          <p className="godown-filter">
            <span className="chip active">At {page.godown}</span>{' '}
            <a href={itemHref(item.item_id, props.query)}>Show every godown</a>
            <span className="card-small-note"> · The movements and months are at this godown only; the cards are the item's whole.</span>
          </p>
        )}
        {page.truncated && <Alert type="warning" showIcon message="Only the first movements are shown: choose a shorter period." />}
        <section className="card" aria-label="Stock item lists">
          <Tabs
            items={[
              {
                key: 'movements',
                label: 'Movements',
                children: (
                  <ExplorerTable id="stock-movements" label="Movements" columns={movementColumns(page, props.companies, props.query)}
                    rows={page.movements.map((m, row) => ({ ...m, row }))} rowKey={(m) => String(m.row)} totalLabel="Total" />
                ),
              },
              {
                key: 'monthly',
                label: 'Month by month',
                children: <ExplorerTable id="stock-item-months" label="Month by month" columns={MONTH_COLUMNS} rows={page.months} rowKey={(m) => m.month} />,
              },
              {
                key: 'godowns',
                label: 'By godown and batch',
                children: <GodownSections sections={page.by_godown} query={props.query} withItem={false} id="stock-item-godowns" />,
              },
            ]}
          />
        </section>
      </>
    )
  }
  return (
    <ReportFrame {...props} title={page?.item.name ?? 'Stock item'} page="stock-item" period={page?.period} combined={(page?.item.companies.length ?? 0) > 1} help={help}>
      {content}
    </ReportFrame>
  )
}
