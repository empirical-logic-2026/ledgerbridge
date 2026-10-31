// The Profit & Loss report page (docs/design/dashboard.md Section 0.1, screen 6): our stored
// Profit & Loss in the source's layout and order, a column per company (or month or quarter)
// plus the total, last year and the change; the toolbar (Columns, Group by, Filters, Export
// CSV) and the options side panel. Figures: core/statement_report.py
// (GET /api/v1/reports/profit-loss).

import { Alert, Button, Checkbox, Dropdown, Skeleton, Tooltip, Typography } from 'antd'
import type { Company, StatementReport } from '../../api/types.ts'
import { formatDate, formatExact, toScaled } from '../../format.ts'
import { download } from '../../reporting/download.ts'
import { OptionsPanel, type Related } from '../../reporting/OptionsPanel.tsx'
import {
  buildCsv,
  cellValue,
  COLUMN_CHOICES,
  formatCell,
  optionsQuery,
  shownColumns,
  shownLines,
  unitFor,
  type ColumnChoice,
  type ReportOptions,
  type View,
} from '../../reporting/reportTable.ts'
import type { Query } from '../../router.ts'
import { COMBINED_NOTE } from './DashboardHome.tsx'

const VIEWS: { key: View; label: string }[] = [
  { key: 'company', label: 'Company by company' },
  { key: 'month', label: 'Month by month' },
  { key: 'quarter', label: 'Quarter by quarter' },
]
const GROUP_LABEL: Record<View, string> = { company: 'Company', month: 'Month', quarter: 'Quarter' }

interface Props {
  companies: Company[] // the selected ones
  report: StatementReport | undefined
  loading: boolean
  error: Error | null
  options: ReportOptions
  onOptions: (change: Record<string, string | string[] | undefined>) => void
  panelOpen: boolean
  onPanel: (open: boolean) => void
  query: Query
  currentQuery: string
  onApplyView: (query: string) => void
  related: Related[]
}

function Help({ sourceName }: { sourceName: string }) {
  return (
    <>
      <p>
        The Profit &amp; Loss of the companies and period you chose, in {sourceName}'s own layout and order: sales, the cost of sales with opening and
        closing stock, gross profit, the other incomes and expenses, and net profit.
      </p>
      <p>
        <strong>Where the figures come from:</strong> our statements, rebuilt from the books after every sync and checked line by line against{' '}
        {sourceName}'s own at each month end. A period's figure is the statement at its end less the one just before its start. Several companies are
        added together without inter-company eliminations.
      </p>
      <p>
        <strong>To compare with {sourceName}:</strong> open the company's Profit &amp; Loss A/c, set the same period (F2), and compare line by line. The
        status above says whether every line already matched when it was last checked.
      </p>
    </>
  )
}

function Table({ report, options }: { report: StatementReport; options: ReportOptions }) {
  const columns = shownColumns(report, options)
  const unit = unitFor(report)
  return (
    <div className="report-table-wrap">
      <table className="report-table">
        <thead>
          <tr>
            <th scope="col">Particulars</th>
            {columns.map((c) => (
              <th key={c.key} scope="col" className="num">
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {shownLines(report, options).map((line) => (
            <tr key={line.key} className={`line-${line.level}`}>
              <th scope="row">{line.label}</th>
              {columns.map((c) => {
                const value = cellValue(line, c)
                if (value === null) return <td key={c.key} className="num muted">—</td>
                const negative = toScaled(value) < 0n
                if (c.kind === 'amount') {
                  return (
                    <td key={c.key} className={negative ? 'num negative' : 'num'}>
                      <Tooltip title={formatExact(value)}>{formatCell(value, unit)}</Tooltip>
                    </td>
                  )
                }
                const text = `${negative ? '' : c.kind === 'change' ? '▲ ' : ''}${value.replace(/^-/, c.kind === 'change' ? '▼ ' : '-').replace(/\.0$/, '')}%`
                // Green when the change is good for the business (sales or profit up, costs
                // down), crimson when sales or profit fall, neutral for costs going up.
                const good = negative !== line.higher_is_better
                const tone = good ? 'good' : line.higher_is_better ? 'bad' : 'neutral'
                return (
                  <td key={c.key} className={c.kind === 'change' ? `num change ${tone}` : 'num'}>
                    {text}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="report-note">
        Amounts in {unit === 'lakh' ? '₹ lakh' : '₹'}; hover over an amount for the exact figure. Click-through to ledgers comes with the Balance Sheet
        and Trial Balance.
      </p>
    </div>
  )
}

export function ProfitLoss(props: Props) {
  const { report, options, companies } = props
  const sourceName = companies[0]?.health.source_name ?? 'the source'
  const names = companies.map((c) => c.name).join(' + ')
  const setColumns = (columns: ColumnChoice[]) => props.onOptions(optionsQuery({ ...options, columns }))
  const exportCsv = () => report && download('profit-and-loss.csv', buildCsv(report, options))
  const columnsMenu = (
    <div className="dropdown-panel">
      <Checkbox.Group value={options.columns} onChange={(v) => setColumns(v as ColumnChoice[])} className="options-list">
        {COLUMN_CHOICES.map((c) => (
          <Checkbox key={c.key} value={c.key}>
            {c.label}
          </Checkbox>
        ))}
      </Checkbox.Group>
    </div>
  )
  const filtersMenu = (
    <div className="dropdown-panel options-list">
      <Checkbox checked={options.showSub} onChange={(e) => props.onOptions(optionsQuery({ ...options, showSub: e.target.checked }))}>
        Lines inside blocks (e.g. Opening Stock)
      </Checkbox>
      <Checkbox checked={options.hideZero} onChange={(e) => props.onOptions(optionsQuery({ ...options, hideZero: e.target.checked }))}>
        Hide lines that are zero
      </Checkbox>
    </div>
  )
  return (
    <div className={props.panelOpen ? 'report-page with-panel' : 'report-page'}>
      <div className="report-main">
        <div className="report-head">
          <div>
            <Typography.Title level={2} className="report-title">
              Profit &amp; Loss · {names}
            </Typography.Title>
            {report && (
              <Typography.Text type="secondary">
                {formatDate(report.period_start)} to {formatDate(report.period_end)}
                {report.combined ? ` · ${COMBINED_NOTE}` : ''}
              </Typography.Text>
            )}
          </div>
          <div className="report-toolbar">
            <Dropdown popupRender={() => columnsMenu} trigger={['click']}>
              <Button>Columns ▾</Button>
            </Dropdown>
            <Dropdown
              trigger={['click']}
              menu={{
                items: VIEWS.map((v) => ({ key: v.key, label: v.label })),
                selectable: true,
                selectedKeys: [options.view],
                onClick: ({ key }) => props.onOptions(optionsQuery({ ...options, view: key as View })),
              }}
            >
              <Button>Group by: {GROUP_LABEL[options.view]} ▾</Button>
            </Dropdown>
            <Dropdown popupRender={() => filtersMenu} trigger={['click']}>
              <Button>Filters ▾</Button>
            </Dropdown>
            <Button type="primary" onClick={exportCsv} disabled={!report || report.lines.length === 0}>
              Export CSV
            </Button>
            {!props.panelOpen && <Button onClick={() => props.onPanel(true)}>Options</Button>}
          </div>
        </div>
        {props.error ? (
          <Alert type="error" showIcon message="The Profit & Loss couldn't be loaded." description={props.error.message} />
        ) : props.loading || !report ? (
          <Skeleton active paragraph={{ rows: 10 }} />
        ) : report.reason ? (
          <Alert type="info" showIcon message="No Profit & Loss for this period" description={`${report.reason}.`} />
        ) : (
          <>
            {report.shifted && (
              <p className="report-note">
                Months ending on the 30th (or in February) run to the 2nd of the next month: {sourceName}'s statements exist only for the 1st, 2nd and
                31st (Educational mode).
              </p>
            )}
            {report.last_year_reason && options.columns.includes('last') && <p className="report-note">No comparison with last year: {report.last_year_reason}.</p>}
            <Table report={report} options={options} />
          </>
        )}
      </div>
      {props.panelOpen && (
        <OptionsPanel
          title="Profit & Loss options"
          page="profit-loss"
          matching={report?.matching}
          companiesLabel={companies.length === 1 ? companies[0].name : companies.length === 2 ? 'both companies' : `all ${companies.length} companies`}
          sourceName={sourceName}
          views={VIEWS}
          view={options.view}
          onView={(view) => props.onOptions(optionsQuery({ ...options, view }))}
          extraViews={
            <>
              <p className="options-muted">Always in {sourceName}'s layout and order.</p>
              <Checkbox checked={options.asPercent} onChange={(e) => props.onOptions(optionsQuery({ ...options, asPercent: e.target.checked }))}>
                As % of sales
              </Checkbox>
            </>
          }
          columns={[...COLUMN_CHOICES, { key: 'budget' as ColumnChoice, label: 'Budget (later)', disabled: true }]}
          shown={options.columns}
          onColumns={setColumns}
          related={props.related}
          query={props.query}
          currentQuery={props.currentQuery}
          onApplyView={props.onApplyView}
          onExport={exportCsv}
          help={<Help sourceName={sourceName} />}
          onClose={() => props.onPanel(false)}
        />
      )}
    </div>
  )
}
