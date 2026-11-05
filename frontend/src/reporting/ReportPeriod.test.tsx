import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ReportPeriod } from './ReportPeriod.tsx'

describe('report date display', () => {
  it('shows the active date filters and the Balance Sheet clarification', () => {
    render(<ReportPeriod start="2026-04-01" end="2026-11-04" balanceSheet />)
    const period = screen.getByRole('group', { name: 'Reporting period' })
    expect(period).toHaveTextContent(/From Date:\s*01-Apr-2026/)
    expect(period).toHaveTextContent(/To Date:\s*04-Nov-2026/)
    expect(period).toHaveTextContent('Reporting period: 01-Apr-2026 to 04-Nov-2026')
    expect(period).toHaveTextContent('Balances are calculated as of the To Date.')
  })
})
