// The Cost Centres page and one cost centre's page (RPT-014): every cost centre by name and
// category across the selected companies, with its allocations month by month and in total;
// a name opens its page with the allocations voucher by voucher (the drill-down). Amounts keep
// the line's sign (debit positive). Figures: core/cost_centres.py
// (GET /api/v1/cost-centres and .../{id}).

import { Alert, Typography } from 'antd'
import { ErrorState } from '../../components/loading/ErrorState.tsx'
import { Loading } from '../../components/loading/Loading.tsx'
import type { AllocationOut, CentreOut, CentrePageOut, CentresOut, Company } from '../../api/types.ts'
import { formatMonth } from '../../format.ts'
import type { ExplorerColumn } from '../../reporting/explorer.ts'
import { ExplorerTable } from '../../reporting/ExplorerTable.tsx'
import { ReportFrame, type PanelProps } from '../../reporting/ReportFrame.tsx'
import type { Query } from '../../router.ts'
import { builtHref } from '../../shell/nav.ts'

interface ListProps extends PanelProps {
  companies: Company[] // the selected ones
  centres: CentresOut | undefined
  loading: boolean
  error: Error | null
  onRetry?: () => void // ask again after an error
}

interface PageProps extends PanelProps {
  companies: Company[]
  centre: CentrePageOut | undefined
  loading: boolean
  error: Error | null
  onRetry?: () => void // ask again after an error
}

/** A cost centre's page, keeping the selection. */
function centreHref(id: number, query: Query): string | undefined {
  return builtHref(['pnl', 'cost-centres', String(id)], query)
}

function companyNames(companies: Company[], ids: number[]): string {
  const names = new Map(companies.map((c) => [c.id, c.name]))
  return ids.map((c) => names.get(c) ?? `Company ${c}`).join(', ')
}

function listColumns(centres: CentresOut, companies: Company[], query: Query): ExplorerColumn<CentreOut>[] {
  const months = centres.centres[0]?.months.map((m) => m.month) ?? []
  return [
    { key: 'name', label: 'Cost centre', kind: 'text', value: (c) => c.name, link: (c) => centreHref(c.centre_id, query) },
    { key: 'category', label: 'Cost category', kind: 'text', value: (c) => c.category, groupable: true },
    { key: 'parent', label: 'Under', kind: 'text', value: (c) => c.parent, groupable: true },
    ...months.map(
      (month, i): ExplorerColumn<CentreOut> => ({
        key: `m-${month}`,
        label: formatMonth(month),
        kind: 'amount',
        value: (c) => c.months[i]?.amount ?? '0',
        help: `The allocations to the cost centre in ${formatMonth(month)} (F-CC-001).`,
      }),
    ),
    { key: 'total', label: 'Allocated', kind: 'amount', value: (c) => c.total },
    { key: 'allocations', label: 'Allocations', kind: 'count', value: (c) => c.allocations },
    { key: 'companies', label: 'Companies', kind: 'text', value: (c) => companyNames(companies, c.companies), groupable: true, hidden: !centres.combined },
  ]
}

type Row = AllocationOut & { row: number } // its place in the list (a voucher can allocate twice)

function allocationColumns(page: CentrePageOut, companies: Company[], query: Query): ExplorerColumn<Row>[] {
  return [
    { key: 'month', label: 'Month', kind: 'text', value: (a) => formatMonth(a.date), groupable: true, hidden: true },
    { key: 'date', label: 'Date', kind: 'date', value: (a) => a.date },
    { key: 'type', label: 'Vch Type', kind: 'text', value: (a) => a.voucher_type, groupable: true },
    { key: 'number', label: 'Vch No.', kind: 'text', value: (a) => a.voucher_number, link: (a) => builtHref(['books', 'vouchers', String(a.voucher_id)], query) },
    { key: 'ledger', label: 'Ledger', kind: 'text', value: (a) => a.ledger, groupable: true },
    { key: 'category', label: 'Cost category', kind: 'text', value: (a) => a.category, groupable: true, hidden: true },
    { key: 'amount', label: 'Allocated', kind: 'amount', value: (a) => a.amount },
    { key: 'company', label: 'Company', kind: 'text', value: (a) => companyNames(companies, [a.company]), groupable: true, hidden: page.centre.companies.length < 2 },
  ]
}

function help(sourceName: string) {
  return (
    <>
      <p>
        Every cost centre of the companies you chose, by name and category: the same cost centre in several companies is one row, its allocations
        added together. Each amount is the part of a voucher line allocated to the cost centre, with the line's sign (debits positive, credits
        negative). A cost centre's own allocations only: the ones under it have their own rows.
      </p>
      <p>
        <strong>Where the figures come from:</strong> the cost-centre allocations of every voucher line (also those under an item invoice's
        lines), checked at each validation against {sourceName}'s own cost-centre totals.
      </p>
      <p>
        <strong>To compare with {sourceName}:</strong> the Cost Centre Break-up (Display More Reports → Statements of Accounts → Cost Centres) for
        the same period; there a cost centre includes the ones under it.
      </p>
    </>
  )
}

export function CostCentres(props: ListProps) {
  const { centres } = props
  let content: React.ReactNode
  if (props.error) {
    content = <ErrorState message="The cost centres couldn't be loaded." error={props.error} onRetry={props.onRetry} />
  } else if (props.loading || !centres) {
    content = <Loading shape="report" />
  } else if (centres.centres.length === 0) {
    content = <Alert type="info" showIcon message="No cost centres in the companies you chose." />
  } else {
    content = (
      <ExplorerTable
        id="cost-centres"
        label="Cost centres"
        columns={listColumns(centres, props.companies, props.query)}
        rows={centres.centres}
        rowKey={(c) => String(c.centre_id)}
        totalLabel="Total"
      />
    )
  }
  return (
    <ReportFrame {...props} title="Cost centres" page="cost-centres" period={centres?.period} combined={centres?.combined ?? false} help={help}>
      {content}
    </ReportFrame>
  )
}

export function CostCentrePage(props: PageProps) {
  const { centre } = props
  let content: React.ReactNode
  if (props.error) {
    content = <ErrorState message="The cost centre couldn't be loaded." error={props.error} onRetry={props.onRetry} />
  } else if (props.loading || !centre) {
    content = <Loading shape="report" />
  } else {
    content = (
      <>
        <Typography.Paragraph className="muted">
          {[centre.centre.category, centre.centre.parent && `Under ${centre.centre.parent}`, `${centre.centre.allocations} allocations`]
            .filter(Boolean)
            .join(' · ')}
        </Typography.Paragraph>
        {centre.truncated && <Alert type="warning" showIcon message="Only the first allocations are shown: choose a shorter period." />}
        <ExplorerTable
          id="cost-centre-allocations"
          label="Allocations"
          columns={allocationColumns(centre, props.companies, props.query)}
          rows={centre.allocations.map((a, row) => ({ ...a, row }))}
          rowKey={(a) => String(a.row)}
          totalLabel="Total"
        />
      </>
    )
  }
  return (
    <ReportFrame
      {...props}
      title={centre?.centre.name ?? 'Cost centre'}
      page="cost-centre"
      period={centre?.period}
      combined={(centre?.centre.companies.length ?? 0) > 1}
      help={help}
    >
      {content}
    </ReportFrame>
  )
}
