// Shows the active date filters in a consistent, explicit format above reports.

import { formatDate } from '../format.ts'

interface Props {
  start: string
  end: string
  balanceSheet?: boolean
}

export function ReportPeriod({ start, end, balanceSheet = false }: Props) {
  const from = formatDate(start)
  const to = formatDate(end)
  return (
    <div className="report-period" role="group" aria-label="Reporting period">
      <div>
        <strong>From Date:</strong> {from}
        <span className="report-period-separator"> · </span>
        <strong>To Date:</strong> {to}
      </div>
      <div>Reporting period: {from} to {to}</div>
      {balanceSheet && <div className="muted">Balances are calculated as of the To Date.</div>}
    </div>
  )
}
