// The statement table: current, previous and change columns, section headings, totals and
// links; without a comparison only the current column.

import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { StatementChange, StatementTable, type StatementSection } from './StatementTable.tsx'

const sections: StatementSection[] = [
  {
    key: 'assets',
    title: 'Assets',
    rows: [
      { key: 'cash', label: 'Cash', level: 'sub', current: '10', previous: '8', change: <StatementChange change="25.0" />, to: '#/cash-flow/movement' },
      { key: 'total', label: 'Total assets', kind: 'total', current: '10', previous: '8' },
    ],
  },
]

describe('the statement table', () => {
  it('shows each line with this period, the comparison and the change, under its section', () => {
    render(<StatementTable label="Test statement" compared sections={sections} columns={{ label: 'Particulars', current: 'Now', previous: 'Before', change: 'Change' }} />)
    const table = screen.getByRole('table', { name: 'Test statement' })
    expect(table.parentElement).toHaveClass('report-table-wrap')
    expect(within(table).getAllByRole('columnheader').map((h) => h.textContent)).toEqual(['Particulars', 'Now', 'Before', 'Change'])
    expect(within(table).getByRole('rowheader', { name: 'Assets' }).closest('tr')).toHaveClass('line-section')
    const cash = within(table).getByRole('link', { name: 'Cash' })
    expect(cash).toHaveAttribute('href', '#/cash-flow/movement')
    expect(cash.closest('tr')).toHaveClass('line-sub')
    expect(cash.closest('tr')).toHaveTextContent('Cash108▲ 25%')
    const total = within(table).getByText('Total assets').closest('tr')
    expect(total).toHaveClass('line-total')
    expect(total).toHaveTextContent('—') // no change given
  })

  it('shows only this period without a comparison', () => {
    render(<StatementTable label="Test statement" compared={false} sections={sections} columns={{ label: 'Particulars', current: 'Now' }} />)
    const table = screen.getByRole('table', { name: 'Test statement' })
    expect(within(table).getAllByRole('columnheader')).toHaveLength(2)
    expect(within(table).getByRole('rowheader', { name: 'Assets' })).toHaveAttribute('colspan', '2')
  })

  it('colours a change by whether it is good for the business', () => {
    const { rerender } = render(<StatementChange change="12.0" higherIsBetter />)
    expect(screen.getByText('▲ 12%')).toHaveClass('good')
    rerender(<StatementChange change="9.0" higherIsBetter={false} />)
    expect(screen.getByText('▲ 9%')).toHaveClass('neutral') // a cost going up
    rerender(<StatementChange change="-1.1" higherIsBetter points />)
    expect(screen.getByText('▼ 1.1 pts')).toHaveClass('bad')
    rerender(<StatementChange change={null} higherIsBetter />)
    expect(screen.getByText('—')).toHaveClass('muted')
  })
})
