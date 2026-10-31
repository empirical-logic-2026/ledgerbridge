import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { App as AntApp } from 'antd'
import App from './App.tsx'
import type { Company, Home, Periods } from './api/types.ts'

// ECharts needs a real canvas; the wrapper is exercised in the browser, not jsdom.
vi.mock('./components/EChart.tsx', () => ({ EChart: () => <div data-testid="chart" /> }))

const health = {
  last_sync_at: '2026-10-30T10:00:00',
  validation_status: 'passed',
  validated_as_of: '2026-10-02',
  validated_at: '2026-10-30T10:00:00',
  source_name: 'Tally',
  source_loaded: true,
  source_checked_at: '2026-10-30T10:00:00',
  source_checked_by: 'sync',
}
const companies: Company[] = [
  { id: 3, code: 'ALPHA', name: 'Alpha', books_from: '2025-04-01', fy_start_month: 4, health },
  {
    id: 4,
    code: 'BETA',
    name: 'Beta',
    books_from: '2025-04-01',
    fy_start_month: 4,
    health: { ...health, source_loaded: false },
  },
]
const periods: Periods = {
  financial_years: [{ start_year: 2026, label: 'FY 2026-27', start: '2026-04-01', end: '2027-03-31' }],
  as_at_dates: ['2026-09-30'],
}
const figure = (value: string | null, last: string | null = null, pct: string | null = null) => ({
  value,
  last_year: last,
  change_pct: pct,
})
const home: Home = {
  companies: [3, 4],
  combined: true,
  period: { start: '2026-04-01', end: '2026-09-30', months: [] },
  profit_loss: {
    available: true,
    reason: null,
    as_of: '2026-10-02',
    shifted: true,
    last_year_reason: null,
    net_sales: figure('482000000.0000', '430357142.8571', '12.0'),
    cost_of_sales: figure('331000000.0000', '303669724.7706', '9.0'),
    gross_profit: figure('151000000.0000'),
    net_profit: figure('62400000.0000'),
  },
  balance_sheet: {
    available: true,
    reason: null,
    as_of: '2026-10-02',
    total_assets: '628000000',
    current_assets: '413000000',
    current_liabilities: '227000000',
    capital_and_reserves: '284000000',
  },
  balances: {
    as_of: '2026-09-30',
    cash_and_bank: '11500000',
    receivables: '98600000',
    payables: '74200000',
    stock_value: null,
    stock_value_as_of: null,
  },
  monthly: [{ month: '2026-04-01', sales: '8000000', purchases: '5000000' }],
  channels: [
    { name: 'Online', net_sales: '142000000' },
    { name: 'Others', net_sales: '104000000' },
  ],
  by_company: [
    { company: 3, net_sales: '342000000', share_pct: '71.0' },
    { company: 4, net_sales: '140000000', share_pct: '29.0' },
  ],
}

let requests: string[] = []

function stubApi(answers: Record<string, unknown>) {
  requests = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      requests.push(url)
      const path = new URL(url).pathname
      if (!(path in answers)) return new Response(JSON.stringify({ detail: 'Not found' }), { status: 404 })
      return new Response(JSON.stringify(answers[path]))
    }),
  )
}

function renderApp(hash: string, onMode = vi.fn()) {
  window.location.hash = hash
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <AntApp>
        <App mode="light" onMode={onMode} today="2026-10-30" />
      </AntApp>
    </QueryClientProvider>,
  )
  return onMode
}

const lastHomeRequest = () => requests.filter((r) => r.includes('/api/v1/home')).pop() ?? ''

describe('the dashboard', () => {
  beforeEach(() =>
    stubApi({ '/api/v1/companies': companies, '/api/v1/periods': periods, '/api/v1/home': home }),
  )
  afterEach(() => vi.unstubAllGlobals())

  it('opens on the Dashboard, with the side bar of built pages and its status', async () => {
    renderApp('#/')
    await screen.findByRole('region', { name: 'Profit & Loss' })
    const side = screen.getByRole('navigation', { name: 'Pages' })
    expect(within(side).getByRole('link', { name: 'Dashboard' })).toHaveAttribute('aria-current', 'page')
    expect(within(side).getByRole('link', { name: 'Profit & Loss' })).toHaveAttribute('href', '#/statements/profit-loss')
    expect(within(side).queryByText('Balance Sheet')).toBeNull() // not built yet: not offered
    expect(within(side).queryByText('Sales')).toBeNull() // a group shows once it has a page
    expect(within(side).getByText(/Tally: 1 of 2 loaded · synced .* · all checks passed/)).toBeInTheDocument()
    expect(within(side).getByText('This computer only')).toBeInTheDocument()
    expect(document.querySelector('.top-crumbs')).toHaveTextContent('Overview/Dashboard')
  })

  it('collapses the side bar', async () => {
    renderApp('#/overview/dashboard')
    const side = await screen.findByRole('navigation', { name: 'Pages' })
    fireEvent.click(within(side).getByRole('button', { name: 'Close the side bar' }))
    expect(within(side).queryByRole('link', { name: 'Profit & Loss' })).toBeNull()
    fireEvent.click(within(side).getByRole('button', { name: 'Open the side bar' }))
    expect(within(side).getByRole('link', { name: 'Profit & Loss' })).toBeInTheDocument()
  })

  it('shows the facets the page can apply, and says why the others are off', async () => {
    renderApp('#/overview/dashboard')
    const customer = await screen.findByRole('button', { name: 'Customer (not used on this page)' })
    expect(customer).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Voucher type (not used on this page)' })).toBeDisabled()
  })

  it('copies the page\'s link, which holds the whole selection', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
    renderApp('#/overview/dashboard?company=4&month=2026-05')
    fireEvent.click(await screen.findByRole('button', { name: 'Copy link' }))
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(expect.stringContaining('#/overview/dashboard?company=4&month=2026-05')))
  })

  it('shows the Profit & Loss and Balance Sheet cards, combined, in lakhs and crores', async () => {
    renderApp('#/overview/dashboard')
    const pl = await screen.findByRole('region', { name: 'Profit & Loss' })
    expect(within(pl).getByText('₹48.20 Cr')).toBeInTheDocument()
    expect(within(pl).getByText('▲ 12%')).toHaveClass('good')
    expect(within(pl).getByText('▲ 9%')).toHaveClass('neutral') // costs up: neutral, not red
    expect(within(pl).getByText(/Months ending on the 30th .* run to the 2nd of the next month/)).toBeInTheDocument()
    const bs = screen.getByRole('region', { name: 'Balance Sheet' })
    expect(within(bs).getByText('₹62.80 Cr')).toBeInTheDocument()
    expect(within(screen.getByRole('region', { name: 'Stock value' })).getByText('—')).toBeInTheDocument()
    expect(screen.getByText(/without inter-company eliminations/)).toBeInTheDocument()
    expect(screen.getByText('71%')).toBeInTheDocument()
    expect(screen.getByTestId('chart')).toBeInTheDocument()
  })

  it('marks each company loaded or not loaded, as the last check found it', async () => {
    renderApp('#/overview/dashboard')
    fireEvent.click(await screen.findByRole('button', { name: 'Company: All combined ▾' }))
    const alpha = await screen.findByRole('button', { name: /Alpha/ })
    expect(within(alpha).getByText('loaded')).toBeInTheDocument()
    expect(within(screen.getByRole('button', { name: /Beta/ })).getByText('not loaded')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'All combined' })).toHaveAttribute('aria-pressed', 'true')
  })

  it('asks for the months up to now by default, and any company combination chosen', async () => {
    renderApp('#/overview/dashboard')
    await screen.findByRole('region', { name: 'Profit & Loss' })
    const asked = lastHomeRequest()
    expect(asked).toContain('company=3&company=4')
    expect(asked).toContain('month=2026-04')
    expect(asked).toContain('month=2026-10')
    expect(asked).not.toContain('month=2026-11')
    fireEvent.click(screen.getByRole('button', { name: 'Company: All combined ▾' }))
    fireEvent.click(await screen.findByRole('button', { name: /Beta/ }))
    expect(window.location.hash).toContain('company=4')
  })

  it('takes chosen months, or a date range typed as DD-MMM-YYYY', async () => {
    renderApp('#/overview/dashboard?month=2026-04&month=2026-06')
    await screen.findByRole('region', { name: 'Profit & Loss' })
    expect(lastHomeRequest()).toMatch(/month=2026-04&month=2026-06.*compare=true/)
    fireEvent.click(screen.getByRole('button', { name: /FY 2026-27 · Apr–Jun \(some months\) · vs last year/ }))
    const from = await screen.findByLabelText('From')
    fireEvent.change(from, { target: { value: '15-Apr-2026' } })
    fireEvent.blur(from)
    expect(window.location.hash).toContain('from=2026-04-15')
    expect(window.location.hash).not.toContain('month=')
  })

  it('shows why profit is missing', async () => {
    stubApi({
      '/api/v1/companies': companies,
      '/api/v1/periods': periods,
      '/api/v1/home': {
        ...home,
        profit_loss: {
          ...home.profit_loss,
          available: false,
          shifted: false,
          reason: 'no statement is stored for 15-Sep-2026; choose whole months',
          net_sales: figure(null),
          cost_of_sales: figure(null),
          gross_profit: figure(null),
          net_profit: figure(null),
        },
      },
    })
    renderApp('#/overview/dashboard?from=2026-04-01&to=2026-09-15')
    expect(
      await screen.findByText(/Profit isn't available: no statement is stored for 15-Sep-2026/),
    ).toBeInTheDocument()
    expect(lastHomeRequest()).toContain('date_from=2026-04-01&date_to=2026-09-15')
  })

  it('switches between light and dark', async () => {
    const onMode = renderApp('#/overview/dashboard')
    fireEvent.click(await screen.findByRole('button', { name: 'Switch to dark mode' }))
    expect(onMode).toHaveBeenCalledWith('dark')
  })

  it('says so when no company is visible', async () => {
    stubApi({ '/api/v1/companies': [] })
    renderApp('#/overview/dashboard')
    expect(await screen.findByText('No companies to show yet.')).toBeInTheDocument()
  })

  it('shows the API being unreachable plainly', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    renderApp('#/overview/dashboard')
    expect(await screen.findByText("The dashboard can't reach the data plane.")).toBeInTheDocument()
  })

  it('has a page for unknown addresses', async () => {
    renderApp('#/nowhere')
    expect(await screen.findByText('Choose a page in the side bar.')).toBeInTheDocument()
  })
})

const statement = {
  companies: [3, 4],
  combined: true,
  view: 'company',
  period_start: '2026-04-01',
  period_end: '2026-09-30',
  columns: [
    { key: 'company:3', label: 'Alpha', kind: 'company' },
    { key: 'company:4', label: 'Beta', kind: 'company' },
    { key: 'total', label: 'Total', kind: 'total' },
    { key: 'last_year', label: 'Last year', kind: 'last_year' },
  ],
  lines: [
    {
      key: 'sales accounts', label: 'Sales Accounts', level: 'main', section: 'gross', higher_is_better: true,
      values: { 'company:3': '341260000', 'company:4': '41030000', total: '382290000', last_year: '340100000' },
      pct_of_sales: { 'company:3': '100.0', 'company:4': '100.0', total: '100.0', last_year: '100.0' },
      change_pct: '12.4',
    },
    {
      key: 'net profit', label: 'Net Profit', level: 'detail', section: 'net', higher_is_better: true,
      values: { 'company:3': '50660000', 'company:4': '-4090000', total: '46570000', last_year: '38020000' },
      pct_of_sales: { 'company:3': '14.8', 'company:4': '-10.0', total: '12.2', last_year: '11.2' },
      change_pct: '22.5',
    },
  ],
  reason: null,
  shifted: false,
  last_year_reason: null,
  matching: { matches: true, dates: ['2026-08-31', '2026-10-02'], differing: 0, compared: 40, unchecked: 0 },
}

describe('the Profit & Loss page', () => {
  beforeEach(() => {
    window.localStorage.clear()
    stubApi({ '/api/v1/companies': companies, '/api/v1/periods': periods, '/api/v1/reports/profit-loss': statement })
  })
  afterEach(() => vi.unstubAllGlobals())

  const lastRequest = () => requests.filter((r) => r.includes('/reports/profit-loss')).pop() ?? ''

  it('shows the statement company by company with the total, last year and change', async () => {
    renderApp('#/statements/profit-loss')
    expect(await screen.findByRole('heading', { name: 'Profit & Loss · Alpha + Beta' })).toBeInTheDocument()
    expect(screen.getByText(/without inter-company eliminations/)).toBeInTheDocument()
    const table = await screen.findByRole('table')
    expect(within(table).getAllByRole('columnheader').map((h) => h.textContent)).toEqual([
      'Particulars', 'Alpha', 'Beta', 'Total', 'Last year', 'Change',
    ])
    expect(within(table).getByText('3,822.9')).toBeInTheDocument() // ₹ lakh
    expect(within(table).getByText('-40.9').closest('td')).toHaveClass('negative') // a loss in crimson
    expect(within(table).getByText('▲ 22.5%')).toBeInTheDocument()
    expect(within(screen.getByRole('navigation', { name: 'Pages' })).getByRole('link', { name: 'Profit & Loss' })).toHaveAttribute('aria-current', 'page')
  })

  it('says it matches Tally, explains itself, and links to related pages', async () => {
    renderApp('#/statements/profit-loss')
    const panel = await screen.findByRole('complementary', { name: 'Profit & Loss options' })
    expect(await within(panel).findByRole('status')).toHaveTextContent(/✓ Matches Tally for both companies \(checked at 2 statement dates up to 02-Oct-2026\)/)
    expect(within(panel).getByRole('region', { name: 'What is this?' })).toHaveTextContent(/To compare with Tally/)
    expect(within(panel).getByRole('link', { name: 'Dashboard →' })).toHaveAttribute('href', '#/overview/dashboard')
  })

  it('changes the view and columns through the URL, keeping the selection', async () => {
    renderApp('#/statements/profit-loss?company=3&company=4')
    const panel = await screen.findByRole('complementary', { name: 'Profit & Loss options' })
    fireEvent.click(within(panel).getByLabelText('Month by month'))
    expect(window.location.hash).toContain('view=month')
    expect(window.location.hash).toContain('company=3&company=4')
    await waitFor(() => expect(lastRequest()).toContain('view=month'))
    fireEvent.click(within(panel).getByLabelText('Last year'))
    expect(window.location.hash).toMatch(/col=each&col=total&col=change/)
  })

  it('saves a view in this browser and opens it again', async () => {
    renderApp('#/statements/profit-loss?view=quarter')
    const panel = await screen.findByRole('complementary', { name: 'Profit & Loss options' })
    fireEvent.change(within(panel).getByLabelText('Name of the view'), { target: { value: 'By quarter' } })
    fireEvent.click(within(panel).getByRole('button', { name: '+ Save current view' }))
    window.location.hash = '#/statements/profit-loss'
    fireEvent.click(await within(panel).findByRole('button', { name: 'By quarter' }))
    expect(window.location.hash).toContain('view=quarter')
  })

  it('exports exactly the table as CSV', async () => {
    const created: Blob[] = []
    vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: (b: Blob) => (created.push(b), 'blob:x'), revokeObjectURL: () => {} }))
    renderApp('#/statements/profit-loss')
    await screen.findByRole('table')
    fireEvent.click(screen.getByRole('button', { name: 'Export CSV' }))
    const text = await created[0].text()
    expect(text).toContain('Particulars,Alpha (₹),Beta (₹),Total (₹),Last year (₹),Change (%)')
    expect(text).toContain('Net Profit,50660000.00,-4090000.00,46570000.00,38020000.00,22.5')
  })

  it('closes and reopens the options panel', async () => {
    renderApp('#/statements/profit-loss')
    const panel = await screen.findByRole('complementary', { name: 'Profit & Loss options' })
    fireEvent.click(within(panel).getByRole('button', { name: 'Close the options' }))
    expect(window.location.hash).toContain('panel=0')
    fireEvent.click(await screen.findByRole('button', { name: 'Options' }))
    expect(window.location.hash).not.toContain('panel=0')
  })

  it('opens from the Dashboard card', async () => {
    stubApi({ '/api/v1/companies': companies, '/api/v1/periods': periods, '/api/v1/home': home })
    renderApp('#/overview/dashboard?company=3')
    const pl = await screen.findByRole('region', { name: 'Profit & Loss' })
    expect(within(pl).getByRole('link', { name: 'Open →' })).toHaveAttribute('href', '#/statements/profit-loss?company=3')
  })
})
