// The table explorer (docs/design/dashboard.md Section 0.3): a table with its toolbar:
// Columns, Group by (subtotals per group), a filter, saved views (kept in this browser until
// login, M5) and Export CSV of exactly what is shown. Headers sort; cells with a link open the
// deeper page. The logic is in explorer.ts.

import { Button, Checkbox, Dropdown, Input, Tooltip } from 'antd'
import { explain, formulaOf } from '../help/glossary.ts'
import { useState } from 'react'
import { formatDate } from '../format.ts'
import { Money } from '../components/Money.tsx'
import { download } from './download.ts'
import {
  defaultState,
  explorerCsv,
  filterRows,
  groupRows,
  shownColumns,
  sortRows,
  stateFromText,
  stateToText,
  totals,
  type Cell,
  type ExplorerColumn,
  type ExplorerState,
} from './explorer.ts'
import { deleteView, loadViews, saveView, type SavedView } from './savedViews.ts'

interface Props<R> {
  id: string // names the saved views and the CSV: "sales-top-customers"
  label: string // the table's accessible name
  columns: ExplorerColumn<R>[]
  rows: R[]
  rowKey: (row: R) => string
  sortKey?: string
  descending?: boolean
  groupBy?: string // grouped this way at first (e.g. a register by month)
  pageSize?: number // rows shown before "Show more"
  totalLabel?: string // the total row's first cell; none without it
  note?: string // under the table
}

function Value<R>({ column, value, row }: { column: ExplorerColumn<R>; value: Cell; row?: R }) {
  if (value === null || value === '') return <span className="muted">—</span>
  let shown: React.ReactNode = String(value)
  if (column.kind === 'amount') {
    const text = String(value)
    shown = <Money value={text} />
  } else if (column.kind === 'date') {
    shown = formatDate(String(value))
  } else if (column.kind === 'count') {
    shown = Number(value).toLocaleString('en-IN')
  }
  if (row !== undefined && column.render) shown = column.render(row)
  const to = row !== undefined ? column.link?.(row) : undefined
  const cell = to ? <a href={to}>{shown}</a> : <>{shown}</>
  const hint = row !== undefined ? column.hint?.(row) : undefined
  return hint ? (
    <Tooltip title={hint}>
      <span className="row-hint" data-hint={hint}>{cell}</span>
    </Tooltip>
  ) : (
    cell
  )
}

/** "num" for amounts and counts, "wrap" for long text. */
function cellClass<R>(column: ExplorerColumn<R>): string | undefined {
  if (numeric(column.kind)) return 'num'
  return column.wrap ? 'wrap' : undefined
}

function numeric(kind: string): boolean {
  return kind === 'amount' || kind === 'count'
}

export function ExplorerTable<R>(props: Props<R>) {
  const { columns, rows } = props
  const [state, setState] = useState<ExplorerState>(() => ({ ...defaultState(columns, props.sortKey, props.descending), groupBy: props.groupBy }))
  const [limit, setLimit] = useState(props.pageSize ?? 100)
  const [views, setViews] = useState<SavedView[]>(() => loadViews(`table.${props.id}`))
  const [name, setName] = useState('')
  const change = (next: Partial<ExplorerState>) => setState({ ...state, ...next })
  const shown = shownColumns(columns, state)
  const visible = sortRows(filterRows(rows, columns, state.filter), columns, state)
  const groupable = columns.filter((c) => c.groupable)

  const sortBy = (key: string) =>
    change({ sortKey: key, descending: state.sortKey === key ? !state.descending : numeric(columns.find((c) => c.key === key)?.kind ?? '') })
  const save = () => {
    const trimmed = name.trim()
    if (!trimmed) return
    setViews(saveView(`table.${props.id}`, { name: trimmed, query: stateToText(state) }))
    setName('')
  }

  const columnsMenu = (
    <div className="dropdown-panel">
      <Checkbox.Group
        value={state.columns}
        onChange={(keys) => change({ columns: columns.filter((c) => (keys as string[]).includes(c.key)).map((c) => c.key) })}
        className="options-list"
      >
        {columns.map((c) => (
          <Checkbox key={c.key} value={c.key}>
            {c.label}
          </Checkbox>
        ))}
      </Checkbox.Group>
    </div>
  )
  const viewsMenu = (
    <div className="dropdown-panel options-list">
      {views.length === 0 && <span className="muted">None saved yet (kept in this browser).</span>}
      {views.map((v) => (
        <div key={v.name} className="explorer-view">
          <Button type="link" size="small" onClick={() => setState(stateFromText(v.query, columns))}>
            {v.name}
          </Button>
          <Button type="text" size="small" aria-label={`Delete saved view ${v.name}`} onClick={() => setViews(deleteView(`table.${props.id}`, v.name))}>
            ×
          </Button>
        </div>
      ))}
      <Input size="small" aria-label="Name of the view" placeholder="Name this view" value={name} onChange={(e) => setName(e.target.value)} onPressEnter={save} />
      <Button size="small" onClick={save}>
        + Save current view
      </Button>
    </div>
  )

  const row = (r: R) => (
    <tr key={props.rowKey(r)}>
      {shown.map((c, i) => {
        const Cell = i === 0 ? 'th' : 'td'
        return (
          <Cell key={c.key} scope={i === 0 ? 'row' : undefined} className={cellClass(c)}>
            <Value column={c} value={c.value(r)} row={r} />
          </Cell>
        )
      })}
    </tr>
  )
  const sumRow = (key: string, label: string, sums: Record<string, Cell>, className: string) => (
    <tr key={key} className={className}>
      {shown.map((c, i) =>
        i === 0 ? (
          <th key={c.key} scope="row">
            {label}
          </th>
        ) : (
          <td key={c.key} className={cellClass(c)}>
            {c.key in sums ? <Value column={c} value={sums[c.key]} /> : null}
          </td>
        ),
      )}
    </tr>
  )

  let body: React.ReactNode
  let hidden = 0
  if (state.groupBy) {
    // Every group's subtotal row; its rows until `limit` rows are shown in all.
    const groupLabel = columns.find((c) => c.key === state.groupBy)?.label ?? ''
    let room = limit
    body = groupRows(visible, columns, state.groupBy).map((g) => {
      const shownRows = g.rows.slice(0, Math.max(0, room))
      room -= shownRows.length
      hidden += g.rows.length - shownRows.length
      return [sumRow(`group-${g.key}`, `${groupLabel}: ${g.key || '(none)'} (${g.rows.length})`, g.totals, 'explorer-group'), ...shownRows.map(row)]
    })
  } else {
    hidden = Math.max(0, visible.length - limit)
    body = visible.slice(0, limit).map(row)
  }

  return (
    <div className="explorer">
      <div className="explorer-toolbar">
        <Input.Search
          allowClear
          size="small"
          aria-label={`Filter ${props.label}`}
          placeholder="Filter"
          value={state.filter}
          onChange={(e) => change({ filter: e.target.value })}
          className="explorer-filter"
        />
        <Dropdown popupRender={() => columnsMenu} trigger={['click']}>
          <Button size="small">Columns ▾</Button>
        </Dropdown>
        <Dropdown
          trigger={['click']}
          disabled={groupable.length === 0}
          menu={{
            items: [{ key: '', label: 'No grouping' }, ...groupable.map((c) => ({ key: c.key, label: c.label }))],
            selectable: true,
            selectedKeys: [state.groupBy ?? ''],
            onClick: ({ key }) => change({ groupBy: key || undefined }),
          }}
        >
          <Button size="small">Group by{state.groupBy ? `: ${columns.find((c) => c.key === state.groupBy)?.label}` : ''} ▾</Button>
        </Dropdown>
        <Dropdown popupRender={() => viewsMenu} trigger={['click']}>
          <Button size="small">Saved views ▾</Button>
        </Dropdown>
        <Button size="small" onClick={() => download(`${props.id}.csv`, explorerCsv(rows, columns, state))} disabled={rows.length === 0}>
          Export CSV
        </Button>
      </div>
      <div className="report-table-wrap">
        <table className="report-table explorer-table" aria-label={props.label}>
          <thead>
            <tr>
              {shown.map((c) => (
                <th
                  key={c.key}
                  scope="col"
                  className={cellClass(c)}
                  aria-sort={state.sortKey === c.key ? (state.descending ? 'descending' : 'ascending') : undefined}
                  data-figure={c.kind === 'amount' || c.kind === 'count' ? 'column' : undefined}
                  data-formula={c.kind === 'amount' || c.kind === 'count' ? formulaOf(c.label, c.formula) : undefined}
                >
                  <Tooltip title={[c.help ?? explain(c.label), 'Click to sort.'].filter(Boolean).join(' ')}>
                    <button type="button" className={c.help ?? explain(c.label) ? 'explorer-sort has-help' : 'explorer-sort'} onClick={() => sortBy(c.key)}>
                      {c.label}
                      {state.sortKey === c.key ? (state.descending ? ' ↓' : ' ↑') : ''}
                    </button>
                  </Tooltip>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visible.length === 0 ? (
              <tr>
                <td colSpan={Math.max(1, shown.length)} className="muted">
                  {rows.length === 0 ? 'Nothing in this period.' : 'Nothing matches the filter.'}
                </td>
              </tr>
            ) : (
              body
            )}
          </tbody>
          {props.totalLabel && visible.length > 0 && <tfoot>{sumRow('total', props.totalLabel, totals(visible, columns), 'explorer-total')}</tfoot>}
        </table>
      </div>
      {hidden > 0 && (
        <Button size="small" onClick={() => setLimit(limit + (props.pageSize ?? 100))}>
          Show more ({hidden.toLocaleString('en-IN')} not shown)
        </Button>
      )}
      {props.note && <p className="report-note">{props.note}</p>}
    </div>
  )
}
