// Data › Explore (RPT-014; ADR-049): a screen for the table explorer's datasets (voucher lines,
// vouchers, cost allocations, GST lines, inventory lines): choose a dataset, its columns or
// group-bys (up to four, with subtotals and the total), its measures and filters; sort and page
// through the result; keep the choices as a saved view (this browser) and export the same
// result as CSV. The choices live in the page's URL (`e_` keys), so a link or a saved view
// opens the same result. The dates follow the top bar's period unless set here. Figures: the
// dataset API (api/v1/datasets.py); each measure names its formula (F-TRN-001, F-STK-014, ...).

import { Button, Input, Select, Space, Typography } from 'antd'
import { Fragment, useState } from 'react'
import { API_BASE_URL, queryString } from '../../api/client.ts'
import { useDatasetResult, useDatasets, useDatasetValues } from '../../api/queries.ts'
import type { Company, DatasetInfo, DatasetResult, Row } from '../../api/types.ts'
import { ErrorState } from '../../components/loading/ErrorState.tsx'
import { Loading } from '../../components/loading/Loading.tsx'
import { Money } from '../../components/Money.tsx'
import { PageNote } from '../../components/PageNote.tsx'
import { ReportFrame, type PanelProps } from '../../reporting/ReportFrame.tsx'
import { deleteView, loadViews, saveView, type SavedView } from '../../reporting/savedViews.ts'
import { updateQuery, useRoute } from '../../router.ts'
import { exploreNote } from './exploreWords.ts'

interface Props extends PanelProps {
  companies: Company[]
  companyIds: number[]
  period: { from: string; to: string } | undefined
}

const PAGE_SIZE = 100

/** The page's choices, read from its URL (`e_` keys). */
interface Choices {
  dataset: string | undefined
  groupBy: string[]
  columns: string[]
  measures: string[]
  sort: string | undefined
  page: number
  filters: Record<string, string[]> // filter key -> values (ids, or one date or amount)
}

function readChoices(query: URLSearchParams): Choices {
  const filters: Record<string, string[]> = {}
  for (const [key, value] of query.entries()) {
    if (key.startsWith('e_f_')) (filters[key.slice(4)] ??= []).push(value)
  }
  return {
    dataset: query.get('e_dataset') ?? undefined,
    groupBy: query.getAll('e_group'),
    columns: query.getAll('e_col'),
    measures: query.getAll('e_measure'),
    sort: query.get('e_sort') ?? undefined,
    page: Math.max(1, Number(query.get('e_page') ?? '1') || 1),
    filters,
  }
}

/** The URL change that sets the choices (every `e_` key; the others kept). */
function writeChoices(c: Choices, old: URLSearchParams): Record<string, string[] | string | undefined> {
  const change: Record<string, string[] | string | undefined> = {}
  for (const key of old.keys()) if (key.startsWith('e_f_')) change[key] = undefined
  for (const [key, values] of Object.entries(c.filters)) change[`e_f_${key}`] = values
  return { ...change, e_dataset: c.dataset, e_group: c.groupBy, e_col: c.columns, e_measure: c.measures, e_sort: c.sort, e_page: c.page > 1 ? String(c.page) : undefined }
}

/** The API's parameters for the choices: the period's dates unless the page sets them. */
function apiParams(c: Choices, info: DatasetInfo, companies: number[], period: Props['period']): Record<string, unknown> {
  const filters = { ...c.filters }
  const offered = new Set(info.filters.map((f) => f.key))
  if (period && offered.has('date_from') && !filters.date_from) filters.date_from = [period.from]
  if (period && offered.has('date_to') && !filters.date_to) filters.date_to = [period.to]
  return {
    group_by: c.groupBy,
    column: c.groupBy.length ? [] : c.columns,
    measure: c.measures,
    sort: c.sort,
    page: c.page,
    page_size: PAGE_SIZE,
    company: companies,
    ...Object.fromEntries(Object.entries(filters).filter(([k]) => offered.has(k) && k !== 'company')),
  }
}

function IdsFilter({ dataset, filterKey, label, values, companies, onChange }: {
  dataset: string; filterKey: string; label: string; values: string[]; companies: number[]; onChange: (values: string[]) => void
}) {
  const [search, setSearch] = useState('')
  const options = useDatasetValues(dataset, filterKey, search, companies)
  return (
    <Select mode="multiple" allowClear showSearch filterOption={false} onSearch={setSearch} placeholder={label} aria-label={label}
      className="explore-filter" value={values} loading={options.isFetching}
      options={(options.data ?? []).map((v) => ({ value: String(v.id), label: v.label }))}
      onChange={(next: string[]) => onChange(next)} />
  )
}

function cell(row: Row, key: string): string {
  const found = row.keys[key]
  return found?.label ?? (found?.id !== undefined ? String(found.id) : '')
}

function measureCell(value: string | number | undefined, isCount: boolean) {
  if (value === undefined || value === null) return '—'
  return isCount ? Number(value).toLocaleString('en-IN') : <Money value={String(value)} />
}

function ResultTable({ info, result }: { info: DatasetInfo; result: DatasetResult }) {
  const keys = result.group_by.length ? result.group_by : result.columns
  const label = (key: string) => info.dimensions.find((d) => d.key === key)?.label ?? key
  const measures = result.measures.map((m) => info.measures.find((x) => x.key === m)!).filter(Boolean)
  const isCount = (key: string) => /count|lines|allocations/.test(key)
  // Subtotals go after the last row of their group on this page (`level` = outer groups).
  const subtotalsAfter = (index: number): Row[] => {
    const row = result.rows[index]
    const next = result.rows[index + 1]
    return result.subtotals.filter((s) => {
      const level = s.level ?? 0
      const outer = result.group_by.slice(0, level)
      const ours = outer.every((k) => String(s.keys[k]?.id) === String(row.keys[k]?.id))
      const ends = !next || outer.some((k) => String(next.keys[k]?.id) !== String(row.keys[k]?.id))
      return ours && ends
    }).sort((a, b) => (b.level ?? 0) - (a.level ?? 0))
  }
  return (
    <div className="report-table-wrap">
      <table className="report-table explorer-table" aria-label={`${info.label} result`}>
        <thead>
          <tr>
            {keys.map((k) => <th key={k} scope="col">{label(k)}</th>)}
            {measures.map((m) => <th key={m.key} scope="col" className="num" data-figure="column" data-formula={m.formula} title={`Formula ${m.formula}`}>{m.label}</th>)}
          </tr>
        </thead>
        <tbody>
          {result.rows.length === 0 && (
            <tr><td colSpan={keys.length + measures.length} className="muted">Nothing matches these choices.</td></tr>
          )}
          {result.rows.map((row, i) => (
            <Fragment key={i}>
              <tr>
                {keys.map((k) => <td key={k}>{cell(row, k)}</td>)}
                {measures.map((m) => <td key={m.key} className="num">{measureCell(row.values[m.key], isCount(m.key))}</td>)}
              </tr>
              {subtotalsAfter(i).map((s, j) => (
                <tr key={`s${j}`} className="explorer-group">
                  {keys.map((k, n) => <td key={k}>{n < (s.level ?? 0) ? cell(s, k) : n === (s.level ?? 0) ? 'Subtotal' : ''}</td>)}
                  {measures.map((m) => <td key={m.key} className="num">{measureCell(s.values[m.key], isCount(m.key))}</td>)}
                </tr>
              ))}
            </Fragment>
          ))}
          <tr className="explorer-total">
            {keys.map((k, n) => <td key={k}>{n === 0 ? 'Total' : ''}</td>)}
            {measures.map((m) => <td key={m.key} className="num">{measureCell(result.total[m.key], isCount(m.key))}</td>)}
          </tr>
        </tbody>
      </table>
    </div>
  )
}

function help(sourceName: string) {
  return (
    <>
      <p>
        The datasets behind the dashboard's tables, from the books as {sourceName} holds them. Group by up to four columns for subtotals and a total
        (F-TBL-001, F-TBL-002); each measure names its formula in its column header.
      </p>
      <p>
        <strong>To compare with {sourceName}:</strong> the Day Book or the register of the same vouchers, for the same dates.
      </p>
    </>
  )
}

export function Explore(props: Props) {
  const route = useRoute()
  const catalogue = useDatasets()
  const choices = readChoices(route.query)
  const datasets = catalogue.data ?? []
  const info = datasets.find((d) => d.key === choices.dataset) ?? datasets[0]
  const chosen: Choices | undefined = info && {
    ...choices,
    dataset: info.key,
    measures: choices.measures.length ? choices.measures : info.default_measures,
    columns: choices.columns.length ? choices.columns : info.default_columns,
  }
  const params = chosen && info ? apiParams(chosen, info, props.companyIds, props.period) : undefined
  const result = useDatasetResult(info?.key, params)
  const [views, setViews] = useState<SavedView[]>(() => loadViews('explore'))
  const [viewName, setViewName] = useState('')
  const change = (next: Partial<Choices>) => {
    if (!chosen) return
    updateQuery(route, writeChoices({ ...chosen, page: 1, ...next }, route.query))
  }
  const currentView = () => queryString(Object.fromEntries([...new Set(route.query.keys())].filter((k) => k.startsWith('e_')).map((k) => [k, route.query.getAll(k)]))).slice(1)

  let content: React.ReactNode
  if (catalogue.error) {
    content = <ErrorState message="The datasets couldn't be loaded." error={catalogue.error} onRetry={() => void catalogue.refetch()} />
  } else if (!info || !chosen) {
    content = <Loading shape="report" />
  } else {
    const groupable = info.dimensions.filter((d) => d.groupable)
    const csv = `${API_BASE_URL}/api/v1/datasets/${info.key}/csv${queryString({ ...params, page: undefined, page_size: undefined })}`
    const pages = result.data ? Math.max(1, Math.ceil(result.data.total_rows / PAGE_SIZE)) : 1
    content = (
      <>
        <section className="card explore-controls" aria-label="Choices">
          <Space wrap align="start">
            <Select aria-label="Dataset" className="explore-dataset" value={info.key} onChange={(key: string) => change({ dataset: key, groupBy: [], columns: [], measures: [], sort: undefined, filters: {} })}
              options={datasets.map((d) => ({ value: d.key, label: d.label }))} />
            <Select mode="multiple" aria-label="Group by" placeholder="Group by (up to 4)" className="explore-select" value={chosen.groupBy} maxCount={4}
              onChange={(groupBy: string[]) => change({ groupBy })} options={groupable.map((d) => ({ value: d.key, label: d.label }))} />
            {chosen.groupBy.length === 0 && (
              <Select mode="multiple" aria-label="Columns" placeholder="Columns" className="explore-select" value={chosen.columns}
                onChange={(columns: string[]) => change({ columns })} options={info.dimensions.map((d) => ({ value: d.key, label: d.label }))} />
            )}
            <Select mode="multiple" aria-label="Measures" placeholder="Measures" className="explore-select" value={chosen.measures}
              onChange={(measures: string[]) => change({ measures })} options={info.measures.map((m) => ({ value: m.key, label: m.label }))} />
            <Select allowClear aria-label="Sort by" placeholder="Sort by" className="explore-filter" value={chosen.sort}
              onChange={(sort?: string) => change({ sort })}
              options={[...(chosen.groupBy.length ? chosen.groupBy : chosen.columns), ...chosen.measures].flatMap((k) => {
                const name = info.dimensions.find((d) => d.key === k)?.label ?? info.measures.find((m) => m.key === k)?.label ?? k
                return [{ value: k, label: `${name} ↑` }, { value: `-${k}`, label: `${name} ↓` }]
              })} />
          </Space>
          <Space wrap align="start" className="explore-filters" aria-label="Filters">
            {info.filters.filter((f) => f.key !== 'company').map((f) => {
              const values = chosen.filters[f.key] ?? []
              const set = (next: string[]) => change({ filters: { ...chosen.filters, [f.key]: next.filter(Boolean) } })
              if (f.kind === 'ids') {
                return <IdsFilter key={f.key} dataset={info.key} filterKey={f.key} label={f.label} values={values} companies={props.companyIds} onChange={set} />
              }
              const type = f.kind.startsWith('date') ? 'date' : 'number'
              const shown = values[0] ?? (f.key === 'date_from' ? props.period?.from : f.key === 'date_to' ? props.period?.to : '') ?? ''
              return (
                <Input key={f.key} type={type} aria-label={f.label} addonBefore={f.label} className="explore-filter" value={shown}
                  onChange={(e) => set(e.target.value ? [e.target.value] : [])} />
              )
            })}
          </Space>
          <Space wrap className="explore-actions">
            <a href={csv} className="ant-btn">Export CSV</a>
            <Input aria-label="View name" placeholder="Name this view" value={viewName} onChange={(e) => setViewName(e.target.value)} className="explore-filter" />
            <Button disabled={!viewName.trim()} onClick={() => { setViews(saveView('explore', { name: viewName.trim(), query: currentView() })); setViewName('') }}>Save view</Button>
            {views.length > 0 && (
              <Select aria-label="Saved views" placeholder="Saved views" className="explore-filter" value={null}
                options={views.map((v) => ({ value: v.name, label: v.name }))}
                onChange={(name: string) => {
                  const view = views.find((v) => v.name === name)
                  if (view) updateQuery(route, writeChoices(readChoices(new URLSearchParams(view.query)), route.query))
                }} />
            )}
            {views.length > 0 && (
              <Select aria-label="Delete a saved view" placeholder="Delete a view" className="explore-filter" value={null}
                options={views.map((v) => ({ value: v.name, label: v.name }))} onChange={(name: string) => setViews(deleteView('explore', name))} />
            )}
          </Space>
        </section>
        <section className="card" aria-label="Result">
          {result.error ? (
            <ErrorState message="The result couldn't be loaded." error={result.error} onRetry={() => void result.refetch()} />
          ) : result.isPending || !result.data ? (
            <Loading shape="report" />
          ) : (
            <>
              <ResultTable info={info} result={result.data} />
              <Space className="explore-pages">
                <Button disabled={chosen.page <= 1} onClick={() => change({ page: chosen.page - 1 })}>Previous</Button>
                <Typography.Text>Page {chosen.page} of {pages} · {result.data.total_rows.toLocaleString('en-IN')} rows</Typography.Text>
                <Button disabled={chosen.page >= pages} onClick={() => change({ page: chosen.page + 1 })}>Next</Button>
              </Space>
            </>
          )}
        </section>
      </>
    )
  }
  return (
    <ReportFrame {...props} title="Explore" page="explore" period={undefined} combined={props.companies.length > 1} help={help}>
      <PageNote page="data-explore" note={exploreNote} />
      {content}
    </ReportFrame>
  )
}
