import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { App as AntApp } from 'antd'
import App from './App.tsx'
import type {
  CentrePageOut,
  CentresOut,
  ChannelsOut,
  Company,
  Home,
  MonthlyOut,
  PartiesOut,
  PartyInvoiceOut,
  PartyOut,
  Periods,
  RegisterOut,
  SalesDashboard,
} from './api/types.ts'

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
  { id: 3, code: 'ALPHA', name: 'Alpha', display_name: 'Alpha', books_from: '2025-04-01', fy_start_month: 4, health },
  {
    id: 4,
    code: 'BETA',
    name: 'Beta',
    display_name: 'Beta',
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
  before: last,
  change_pct: pct,
})
const LAST_YEAR = { kind: 'last_year' as const, label: 'Last year', start: '2025-04-01', end: '2025-09-30', months: [] }
const home: Home = {
  companies: [3, 4],
  combined: true,
  period: { start: '2026-04-01', end: '2026-09-30', months: [] },
  compared_with: LAST_YEAR,
  profit_loss: {
    cut: false,
    available: true,
    reason: null,
    as_of: '2026-10-02',
    shifted: true,
    before_reason: null,
    net_sales: figure('482000000.0000', '430357142.8571', '12.0'),
    cost_of_sales: figure('331000000.0000', '303669724.7706', '9.0'),
    gross_profit: figure('151000000.0000'),
    net_profit: figure('62400000.0000'),
    gross_margin_pct: { value: '31.3', before: '29.4', change_pts: '1.9' },
    net_profit_pct: { value: '12.9', before: '14.0', change_pts: '-1.1' },
    other_costs: figure('88600000.0000'),
    cost_of_sales_pct: { value: '68.7', before: '70.6', change_pts: '-1.9' },
    other_costs_pct: { value: '18.4', before: null, change_pts: null },
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
  customers: { value: 1240, before: 1100, change_pct: '12.7' },
  monthly: [{ month: '2026-04-01', sales: '8000000', purchases: '5000000', gross_profit: '2500000', net_profit: '900000' }],
  channels: [
    { name: 'Online', net_sales: '142000000' },
    { name: 'Others', net_sales: '104000000' },
  ],
  by_company: [
    { company: 3, net_sales: '342000000', share_pct: '71.0' },
    { company: 4, net_sales: '140000000', share_pct: '29.0' },
  ],
  trend: [
    { month: '2026-03-01', net_sales: '7000000', gross_profit: null, net_profit: null, cash_and_bank: '10000000', customers: 900 },
    { month: '2026-04-01', net_sales: '8000000', gross_profit: '2500000', net_profit: '900000', cash_and_bank: '11500000', customers: 1240 },
  ],
  summary: [
    { key: 'net_sales', label: 'Net sales', unit: 'amount', higher_is_better: true, value: '482000000', last_year: '430357142.8571', change_pct: '12.0', change_pts: null },
    { key: 'cost_of_sales', label: 'Cost of sales', unit: 'amount', higher_is_better: false, value: '331000000', last_year: '303669724.7706', change_pct: '9.0', change_pts: null },
    { key: 'net_profit_pct', label: 'Net profit %', unit: 'percent', higher_is_better: true, value: '12.9', last_year: '14.0', change_pct: null, change_pts: '-1.1' },
  ],
  summary_reason: null,
  top_customers: [
    { party_id: 11, name: 'Customer One', net_sales: '18400000', share_pct: '3.8', balance: '1161000', overdue: '313000', status: 'overdue', payment_status: 'overdue' },
    { party_id: 12, name: 'Customer Two', net_sales: '9000000', share_pct: '1.9', balance: '0', overdue: '0', status: 'current', payment_status: 'settled' },
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

  it('opens on the Overview, with the top bar of modules and period toggles, and the page header', async () => {
    renderApp('#/')
    await screen.findByRole('region', { name: 'Net sales' })
    const top = screen.getByRole('banner')
    expect(within(top).getByRole('img', { name: 'Empirical Logic' })).toBeInTheDocument()
    expect(within(top).getByText('LedgerBridge')).toBeInTheDocument()
    const modules = within(top).getByRole('navigation', { name: 'Modules' })
    expect(within(modules).getByRole('link', { name: 'Overview' })).toHaveAttribute('aria-current', 'page')
    expect(within(modules).getByRole('link', { name: 'Sales' })).toHaveAttribute('href', '#/sales/dashboard')
    expect(within(modules).getByRole('link', { name: 'P&L & KPIs' })).toHaveAttribute('href', '#/pnl/profit-loss')
    expect(within(modules).getByRole('link', { name: 'Balance Sheet' })).toHaveAttribute('href', '#/balance-sheet/statement')
    expect(within(modules).getByRole('link', { name: 'Data' })).toHaveAttribute('href', '#/data/health')
    expect(within(modules).getByRole('link', { name: 'Parties' })).toHaveAttribute('href', '#/parties/receivables')
    expect(within(top).getByRole('button', { name: 'YTD' })).toHaveAttribute('aria-pressed', 'true') // the default
    expect(screen.getByRole('heading', { level: 1, name: 'Overview' })).toBeInTheDocument()
    expect(screen.getByText('01-Apr-2026 to 30-Oct-2026 · vs previous period')).toBeInTheDocument()
    expect(screen.getByText(/Updated .* ago/)).toBeInTheDocument()
    expect(screen.queryByRole('navigation', { name: 'Pages' })).toBeNull() // no side bar
  })

  it('runs the period toggles to today and asks for the previous period by default (RPT-016)', async () => {
    renderApp('#/overview/dashboard')
    await screen.findByRole('region', { name: 'Net sales' })
    expect(lastHomeRequest()).toContain('date_from=2026-04-01&date_to=2026-10-30&compare=previous&span=year')
    fireEvent.click(screen.getByRole('button', { name: 'MTD' }))
    expect(window.location.hash).toContain('p=mtd')
    await waitFor(() => expect(lastHomeRequest()).toContain('date_from=2026-10-01&date_to=2026-10-30&compare=previous&span=month'))
    fireEvent.click(screen.getByRole('button', { name: 'QTD' }))
    await waitFor(() => expect(lastHomeRequest()).toContain('date_from=2026-10-01&date_to=2026-10-30&compare=previous&span=quarter'))
    fireEvent.click(screen.getByRole('button', { name: 'FY' }))
    await waitFor(() => expect(lastHomeRequest()).toContain('month=2027-03&compare=previous&span=year'))
  })

  it('takes no facets on the Overview', async () => {
    renderApp('#/overview/dashboard')
    await screen.findByRole('region', { name: 'Net sales' })
    expect(screen.queryByRole('combobox', { name: 'Customer' })).toBeNull()
    expect(screen.queryByRole('group', { name: 'Channels' })).toBeNull()
  })

  it('copies the page\'s link, which holds the whole selection', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
    renderApp('#/overview/dashboard?company=4&month=2026-05')
    fireEvent.click(await screen.findByRole('button', { name: 'Copy link' }))
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(expect.stringContaining('#/overview/dashboard?company=4&month=2026-05')))
  })

  it('shows the key cards with sparklines, the charts, the summary against last year and the top customers', async () => {
    renderApp('#/overview/dashboard?compare=1')
    const net = await screen.findByRole('region', { name: 'Net sales' })
    expect(within(net).getByText('₹48.20 Cr')).toBeInTheDocument()
    expect(within(net).getByText('▲ 12% vs last year')).toHaveClass('good')
    expect(net).toHaveClass('kpi-card')
    const gross = screen.getByRole('region', { name: 'Gross profit' })
    expect(within(gross).getByText('₹15.10 Cr')).toBeInTheDocument()
    expect(within(gross).getByText('Gross margin 31.3%')).toBeInTheDocument()
    expect(within(screen.getByRole('region', { name: 'Net profit' })).getByText('Net margin 12.9%')).toBeInTheDocument()
    expect(within(screen.getByRole('region', { name: 'Cash & bank' })).getByText('₹1.15 Cr')).toBeInTheDocument()
    const customers = screen.getByRole('region', { name: 'Customers' })
    expect(within(customers).getByText('1,240')).toBeInTheDocument()
    expect(within(customers).getByText('▲ 12.7% vs last year')).toHaveClass('good')
    expect(screen.getByText(/Months ending on the 30th .* run to the 2nd of the next month/)).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Balance Sheet' })).toBeNull()
    expect(screen.getByRole('region', { name: 'Sales and purchases by month' })).toHaveTextContent(/Gross profit.*Net profit/)
    // Sales by channel: a donut with each channel's share; a channel opens its register.
    const channels = screen.getByRole('group', { name: 'Net sales by channel' })
    expect(within(channels).getByRole('link', { name: 'Online' })).toHaveAttribute('href', expect.stringMatching(/^#\/sales\/register\?.*channel=Online/))
    expect(within(channels).getByText('57.7%')).toBeInTheDocument()
    expect(within(channels).queryByRole('link', { name: 'Others' })).toBeNull()
    // The Profit & Loss summary against last year: a cost going up is neutral, a margin in points.
    const summary = screen.getByRole('table', { name: 'Profit & Loss against last year' })
    expect(within(summary).getByText('▲ 9%')).toHaveClass('neutral')
    expect(within(summary).getByText('▼ 1.1 pts')).toHaveClass('bad')
    // The top customers, each opening their page, with their status.
    const top = screen.getByRole('table', { name: 'Top customers by net sales' })
    expect(within(top).getByRole('link', { name: 'Customer One' })).toHaveAttribute('href', expect.stringMatching(/^#\/sales\/customers\/11/))
    expect(within(top).getByText('Payment Overdue')).toHaveClass('status-bad')
    expect(within(top).getByText('Fully Settled')).toHaveClass('status-good')
    expect(within(top).getByText('Customer has not paid by the due date.')).toBeInTheDocument()
    expect(screen.getByText(/without inter-company eliminations/)).toBeInTheDocument()
    expect(screen.getAllByTestId('chart').length).toBeGreaterThan(1) // the charts and the sparklines
  })

  it('uses legacy customer status fields when payment_status is absent from an older API response', async () => {
    const legacyHome = {
      ...home,
      top_customers: home.top_customers.map(({ payment_status: _paymentStatus, ...customer }) => customer),
    }
    stubApi({ '/api/v1/companies': companies, '/api/v1/periods': periods, '/api/v1/home': legacyHome })
    renderApp('#/overview/dashboard')
    const table = await screen.findByRole('table', { name: 'Top customers by net sales' })
    expect(within(table).getByText('Payment Overdue')).toBeInTheDocument()
    expect(within(table).getByText('Fully Settled')).toBeInTheDocument()
  })

  it('keeps the Overview usable and reports malformed customer entries', async () => {
    const malformedHome = {
      ...home,
      top_customers: [null, ...home.top_customers],
    }
    stubApi({ '/api/v1/companies': companies, '/api/v1/periods': periods, '/api/v1/home': malformedHome })
    renderApp('#/overview/dashboard')

    expect(await screen.findByRole('alert')).toHaveTextContent("Some customer rows couldn't be displayed.")
    const table = screen.getByRole('table', { name: 'Top customers by net sales' })
    expect(within(table).getByRole('link', { name: 'Customer One' })).toBeInTheDocument()
    expect(within(table).getByRole('link', { name: 'Customer Two' })).toBeInTheDocument()
  })

  it('shows the companies as chips, all of them combined unless some are chosen', async () => {
    renderApp('#/overview/dashboard')
    const chips = await screen.findByRole('group', { name: 'Companies' })
    expect(within(chips).getByRole('button', { name: 'All companies' })).toHaveAttribute('aria-pressed', 'true')
    expect(within(chips).getByRole('button', { name: 'Alpha' }).querySelector('.dot-loaded')).not.toBeNull()
    expect(within(chips).getByRole('button', { name: 'Beta' }).querySelector('.dot-not-loaded')).not.toBeNull()
    await waitFor(() => expect(lastHomeRequest()).toContain('company=3&company=4'))
    fireEvent.click(within(chips).getByRole('button', { name: 'Beta' }))
    expect(window.location.hash).toContain('company=4')
  })

  it('takes chosen months, or a date range typed as DD-MMM-YYYY (Custom)', async () => {
    renderApp('#/overview/dashboard?month=2026-04&month=2026-06')
    await screen.findByRole('region', { name: 'Net sales' })
    expect(screen.getByRole('button', { name: 'Custom ▾' })).toHaveAttribute('aria-pressed', 'true')
    expect(lastHomeRequest()).toMatch(/month=2026-04&month=2026-06&compare=previous$/)
    fireEvent.click(screen.getByRole('button', { name: 'Custom ▾' }))
    const from = await screen.findByLabelText('From')
    fireEvent.change(from, { target: { value: '15-Apr-2026' } })
    fireEvent.blur(from)
    expect(window.location.hash).toContain('from=2026-04-15')
    expect(window.location.hash).toContain('p=custom')
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
          gross_margin_pct: { value: null },
          net_profit_pct: { value: null },
        },
        monthly: [{ ...home.monthly[0], gross_profit: null, net_profit: null }],
      },
    })
    renderApp('#/overview/dashboard?from=2026-04-01&to=2026-09-15')
    expect(
      await screen.findByText(/Profit isn't available: no statement is stored for 15-Sep-2026/),
    ).toBeInTheDocument()
    expect(lastHomeRequest()).toContain('date_from=2026-04-01&date_to=2026-09-15')
    expect(within(screen.getByRole('region', { name: 'Net profit' })).getByText('—')).toBeInTheDocument()
    expect(screen.getByText(/No profit marked: each month's profit needs its stored statements/)).toBeInTheDocument()
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
    expect(await screen.findByText('Choose a module in the top bar.')).toBeInTheDocument()
  })
})

const statement = {
  companies: [3, 4],
  combined: true,
  view: 'company',
  period_start: '2026-04-01',
  period_end: '2026-09-30',
  compared_with: LAST_YEAR,
  columns: [
    { key: 'company:3', label: 'Alpha', kind: 'company' },
    { key: 'company:4', label: 'Beta', kind: 'company' },
    { key: 'total', label: 'Total', kind: 'total' },
    { key: 'before', label: 'Last year', kind: 'before' },
  ],
  lines: [
    {
      key: 'sales accounts', label: 'Sales Accounts', level: 'main', section: 'gross', higher_is_better: true,
      values: { 'company:3': '341260000', 'company:4': '41030000', total: '382290000', before: '340100000' },
      pct_of_sales: { 'company:3': '100.0', 'company:4': '100.0', total: '100.0', before: '100.0' },
      change_pct: '12.4',
    },
    {
      key: 'net profit', label: 'Net Profit', level: 'detail', section: 'net', higher_is_better: true,
      values: { 'company:3': '50660000', 'company:4': '-4090000', total: '46570000', before: '38020000' },
      pct_of_sales: { 'company:3': '14.8', 'company:4': '-10.0', total: '12.2', before: '11.2' },
      change_pct: '22.5',
    },
  ],
  reason: null,
  shifted: false,
  before_reason: null,
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
    renderApp('#/statements/profit-loss?from=2026-04-01&to=2026-09-30')
    expect(await screen.findByRole('heading', { name: 'Profit & Loss · Alpha + Beta' })).toBeInTheDocument()
    expect(await screen.findByText(/without inter-company eliminations/)).toBeInTheDocument()
    const table = await screen.findByRole('table')
    expect(within(table).getAllByRole('columnheader').map((h) => h.textContent)).toEqual([
      'Particulars', 'Alpha', 'Beta', 'Total', 'Last year', 'Change',
    ])
    expect(within(table).getByText('3,822.9')).toBeInTheDocument() // ₹ lakh
    expect(within(table).getByText('-40.9').closest('td')).toHaveClass('negative') // a loss in crimson
    expect(within(table).getByText('▲ 22.5%')).toBeInTheDocument()
    const reportPeriod = screen.getByRole('group', { name: 'Reporting period' })
    expect(reportPeriod).toHaveTextContent(/From Date:\s*01-Apr-2026/)
    expect(reportPeriod).toHaveTextContent(/To Date:\s*30-Sep-2026/)
    expect(lastRequest()).toContain('date_from=2026-04-01&date_to=2026-09-30')
    // An older link opens the page in its module (P&L & KPIs).
    expect(within(screen.getByRole('navigation', { name: 'Modules' })).getByRole('link', { name: 'P&L & KPIs' })).toHaveAttribute('aria-current', 'page')
  })

  it('shows the margins, the expense structure and the goal placeholder above the statement', async () => {
    stubApi({ '/api/v1/companies': companies, '/api/v1/periods': periods, '/api/v1/reports/profit-loss': statement, '/api/v1/home': home })
    renderApp('#/pnl/profit-loss?compare=1')
    const tiles = await screen.findByRole('list', { name: 'Margins as % of net sales' })
    expect(within(tiles).getByRole('listitem', { name: 'Gross margin' })).toHaveTextContent('31.3%')
    expect(within(tiles).getByRole('listitem', { name: 'Net margin' })).toHaveTextContent('▼ 1.1 pts vs last year')
    expect(within(tiles).getByText('▼ 1.9 pts vs last year')).toHaveClass('good') // a cost falling is good
    expect(screen.getByRole('region', { name: 'Goal tracker' })).toHaveTextContent(/budgets \(milestone M7b\)/)
    expect(await screen.findByRole('table')).toBeInTheDocument() // the statement below
  })

  it('says it matches Tally under the title, and explains itself on request', async () => {
    renderApp('#/pnl/profit-loss')
    expect(await screen.findByRole('status')).toHaveTextContent(/✓ Matches Tally for both companies \(checked at 2 statement dates up to 02-Oct-2026\)/)
    fireEvent.click(screen.getByRole('button', { name: 'What is this?' }))
    expect(await screen.findByText(/To compare with Tally/)).toBeInTheDocument()
  })

  it('changes the view and columns from the toolbar, through the URL, keeping the selection', async () => {
    renderApp('#/pnl/profit-loss?company=3&company=4')
    await screen.findByRole('table')
    fireEvent.click(screen.getByRole('button', { name: /Group by/ }))
    fireEvent.click(await screen.findByText('Month by month'))
    expect(window.location.hash).toContain('view=month')
    expect(window.location.hash).toContain('company=3&company=4')
    await waitFor(() => expect(lastRequest()).toContain('view=month'))
    fireEvent.click(screen.getByRole('button', { name: 'Columns ▾' }))
    fireEvent.click(await screen.findByLabelText('Compared period'))
    expect(window.location.hash).toMatch(/col=each&col=total&col=change/)
  })

  it('exports exactly the table as CSV', async () => {
    const created: Blob[] = []
    vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: (b: Blob) => (created.push(b), 'blob:x'), revokeObjectURL: () => {} }))
    renderApp('#/pnl/profit-loss')
    await screen.findByRole('table')
    fireEvent.click(screen.getByRole('button', { name: 'Export CSV' }))
    const text = await created[0].text()
    expect(text).toContain('Particulars,Alpha (₹),Beta (₹),Total (₹),Last year (₹),Change (%)')
    expect(text).toContain('Net Profit,50660000.00,-4090000.00,46570000.00,38020000.00,22.5')
  })

  it('has no floating options panel', async () => {
    renderApp('#/pnl/profit-loss')
    await screen.findByRole('table')
    expect(screen.queryByRole('complementary')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Options' })).toBeNull()
  })

  it('explains each column header on hover: what it means and its formula', async () => {
    renderApp('#/pnl/profit-loss')
    const table = await screen.findByRole('table')
    fireEvent.mouseEnter(within(table).getByText('Change'))
    expect(await screen.findByText(/How much the figure moved .*\(F-CMP-001\)/)).toBeInTheDocument()
  })

  it('opens from the Dashboard\'s key figures', async () => {
    stubApi({ '/api/v1/companies': companies, '/api/v1/periods': periods, '/api/v1/home': home })
    renderApp('#/overview/dashboard?company=3')
    const net = await screen.findByRole('region', { name: 'Net profit' })
    expect(within(net).getByRole('link', { name: 'Net profit' })).toHaveAttribute('href', '#/pnl/profit-loss?company=3')
    expect(within(screen.getByRole('region', { name: 'Net sales' })).getByRole('link', { name: 'Net sales' })).toHaveAttribute('href', '#/sales/dashboard?company=3')
    expect(within(screen.getByRole('region', { name: 'Customers' })).getByRole('link', { name: 'Customers' })).toHaveAttribute('href', '#/sales/customers?company=3')
  })
})

const sales: SalesDashboard = {
  companies: [3, 4],
  combined: true,
  period: { start: '2026-04-01', end: '2026-09-30', months: [] },
  compared_with: LAST_YEAR,
  key_figures: {
    net_sales: figure('482000000.0000', '430357142.8571', '12.0'),
    invoices: figure('120', '100', '20.0'),
    average_invoice: figure('4100000.00', null, null),
    sales_returns: figure('10000000.0000', '8000000.0000', '25.0'),
  },
  monthly: [
    { month: '2026-04-01', gross: '250000000', returns: '-5000000', other: '0', net: '245000000', invoices: 60 },
    { month: '2026-05-01', gross: '242000000', returns: '-5000000', other: '0', net: '237000000', invoices: 60 },
  ],
  monthly_by_company: [
    { company: 3, month: '2026-04-01', gross: '140000000', returns: '-3000000', other: '0', net: '137000000' },
    { company: 4, month: '2026-04-01', gross: '110000000', returns: '-2000000', other: '0', net: '108000000' },
    { company: 3, month: '2026-05-01', gross: '132000000', returns: '-3000000', other: '0', net: '129000000' },
    { company: 4, month: '2026-05-01', gross: '110000000', returns: '-2000000', other: '0', net: '108000000' },
  ],
  top_customers: [
    { company: 3, party_id: 11, name: 'Customer One', net_sales: '300000000', invoices: 70, balance: '1161000', overdue: '313000', status: 'overdue', payment_status: 'overdue' },
    { company: 4, party_id: 12, name: 'Customer Two', net_sales: '100000000', invoices: 40, balance: '0', overdue: '0', status: 'current', payment_status: 'settled' },
  ],
  other_customers: '82000000',
  customers: 9,
  largest_invoices: [
    { voucher_id: 501, company: 3, date: '2026-05-04', number: 'S-17', voucher_type: 'Sales', party_id: 11, party: 'Customer One', amount: '50000000' },
    { voucher_id: 502, company: 4, date: '2026-04-09', number: 'S-3', voucher_type: 'Online Sales', party_id: 12, party: 'Customer Two', amount: '20000000' },
  ],
  channels: [
    { name: 'Sales', net_sales: '382000000', share_pct: '79.3' },
    { name: 'Online Sales', net_sales: '100000000', share_pct: '20.7' },
  ],
}

const ageingRow = (id: number, name: string, balance: string, notDue: string, over90: string, uncovered: string) => ({
  party_id: id,
  name,
  balance,
  buckets: { not_due: notDue, days_1_30: '0', days_31_60: '0', days_61_90: '0', over_90: over90 },
  overdue: over90,
  uncovered,
  status: over90 === '0' ? ('current' as const) : ('overdue' as const),
  payment_status: balance.startsWith('-') ? 'advance' : balance === '0' ? 'settled' : over90 === '0' ? 'pending' : 'overdue',
})
const ageingFound = {
  kind: 'customers',
  companies: [3, 4],
  combined: true,
  as_of: '2026-09-30',
  rows: [ageingRow(11, 'Customer One', '1161000', '600000', '400000', '161000'), ageingRow(12, 'Customer Two', '200000', '200000', '0', '0')],
  total: { ...ageingRow(0, 'Total', '1361000', '800000', '400000', '161000') },
}

const sheetLine = (key: string, label: string, section: 'assets' | 'liabilities', value: string, before: string) => ({
  key, label, level: 'main' as const, section, value, before, change_pct: null,
})
const sheetFound = {
  companies: [3, 4],
  combined: true,
  period_start: '2026-04-01',
  period_end: '2026-09-30',
  as_of: '2026-09-30',
  before_as_of: '2026-08-31',
  compared_with: { kind: 'previous' as const, label: 'Previous period', start: '2026-08-01', end: '2026-08-31', months: ['2026-08-01'] },
  reason: null,
  before_reason: null,
  lines: [
    sheetLine('assets:current assets', 'Current Assets', 'assets', '413000000', '400000000'),
    sheetLine('liabilities:capital account', 'Capital Account', 'liabilities', '284000000', '280000000'),
  ],
  totals: [
    { section: 'assets' as const, value: '628000000', before: '600000000', change_pct: '4.7' },
    { section: 'liabilities' as const, value: '628000000', before: '600000000', change_pct: '4.7' },
  ],
  ratios: [
    { key: 'current_ratio', label: 'Current ratio', unit: 'times' as const, formula_id: 'F-RAT-001', value: '1.82', before: '1.75', change: '0.07' },
    { key: 'receivable_days', label: 'Receivable days', unit: 'days' as const, formula_id: 'F-RAT-004', value: '45', before: '40', change: '5' },
  ],
}

describe('the Data module', () => {
  afterEach(() => vi.unstubAllGlobals())

  it("shows each company's sync, checks and whether the source had it, with counts", async () => {
    stubApi({ '/api/v1/companies': companies, '/api/v1/periods': periods })
    renderApp('#/data/health')
    const passed = await screen.findByRole('region', { name: 'Checks passed' })
    expect(passed).toHaveTextContent('2')
    expect(screen.getByRole('region', { name: 'Loaded in the source' })).toHaveTextContent('1')
    const table = screen.getByRole('table', { name: 'Data health by company' })
    expect(within(table).getByText('Beta').closest('tr')?.querySelector('.status-bad')).toHaveTextContent('Not loaded')
    expect(within(table).getAllByText('Passed')).toHaveLength(2)
  })

  it('lists the companies', async () => {
    stubApi({ '/api/v1/companies': companies, '/api/v1/periods': periods })
    renderApp('#/data/companies')
    const table = await screen.findByRole('table', { name: 'Companies' })
    expect(within(table).getByText('ALPHA').closest('tr')).toHaveTextContent('April')
  })
})

describe('the cash movement', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('shows the start, money in and out, the end, and the categories', async () => {
    stubApi({
      '/api/v1/companies': companies,
      '/api/v1/periods': periods,
      '/api/v1/cash-flow': {
        companies: [3, 4], combined: true, start: '2026-04-01', end: '2026-10-30', opening: '1000000', closing: '1200000',
        movements: [
          { key: 'customers', label: 'Customers', inflow: '900000', outflow: '0', net: '900000' },
          { key: 'suppliers', label: 'Suppliers', inflow: '0', outflow: '700000', net: '-700000' },
        ],
        monthly: [{ month: '2026-04-01', inflow: '900000', outflow: '700000' }],
      },
    })
    renderApp('#/cash-flow/movement')
    expect(await screen.findByRole('region', { name: 'Money in' })).toHaveTextContent('₹9.0 L')
    expect(screen.getByRole('region', { name: 'Money out' })).toHaveTextContent('₹7.0 L')
    expect(screen.getByRole('region', { name: 'Cash & bank at the end' })).toHaveTextContent('₹12.0 L')
    const table = screen.getByRole('table', { name: 'Cash movement by what it was for' })
    expect(within(table).getByText('Suppliers').closest('tr')).toHaveTextContent('-₹7,00,000.00')
    expect(screen.getByText(/full cash flow statement \(operating, investing, financing\) is planned separately/)).toBeInTheDocument()
  })
})

describe('the Balance Sheet', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('shows both sides at the two dates with the change, and the ratios as tiles', async () => {
    stubApi({ '/api/v1/companies': companies, '/api/v1/periods': periods, '/api/v1/reports/balance-sheet': sheetFound })
    renderApp('#/balance-sheet/statement?from=2026-04-01&to=2026-09-30')
    const table = await screen.findByRole('table', { name: 'Balance Sheet' })
    expect(within(table).getAllByRole('columnheader').map((h) => h.textContent)).toEqual(['Particulars', '30-Sep-2026', '31-Aug-2026', 'Change'])
    expect(within(table).getByText('Total assets').closest('tr')).toHaveTextContent('₹62.80 Cr')
    expect(within(table).getByText('Total liabilities and capital').closest('tr')).toHaveTextContent('▲ 4.7%')
    const reportPeriod = screen.getByRole('group', { name: 'Reporting period' })
    expect(reportPeriod).toHaveTextContent(/From Date:\s*01-Apr-2026/)
    expect(reportPeriod).toHaveTextContent(/To Date:\s*30-Sep-2026/)
    expect(reportPeriod).toHaveTextContent('Balances are calculated as of the To Date.')
    const request = requests.filter((url) => url.includes('/reports/balance-sheet')).pop() ?? ''
    expect(request).toContain('date_from=2026-04-01&date_to=2026-09-30')
    const liquidity = screen.getByRole('list', { name: 'Liquidity ratios' })
    expect(within(liquidity).getByRole('listitem', { name: 'Current ratio' })).toHaveTextContent('1.82×')
    const days = within(screen.getByRole('list', { name: 'Working capital days' })).getByRole('listitem', { name: 'Receivable days' })
    expect(days).toHaveTextContent('45 days')
    expect(within(days).getByText('▲ 5 days vs previous period')).toHaveClass('bad') // slower collection
  })
})

describe('Receivables with ageing', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('shows the buckets as bars and every customer with their status, as at the period end', async () => {
    stubApi({ '/api/v1/companies': companies, '/api/v1/periods': periods, '/api/v1/ageing/customers': ageingFound })
    renderApp('#/parties/receivables')
    const due = await screen.findByRole('region', { name: 'Balance due' })
    expect(due).toHaveTextContent('₹13.6 L')
    expect(screen.getByRole('region', { name: 'Over 90 days' })).toHaveTextContent('₹4.0 L')
    const bars = screen.getByRole('list', { name: 'Outstanding bills by bucket' })
    expect(within(bars).getByText('Not due').closest('.hbar')).toHaveTextContent('66.7%')
    expect(within(bars).getByText('Over 90 days').closest('.hbar')).toHaveTextContent('33.3%')
    const table = screen.getByRole('table', { name: 'Customers by ageing' })
    expect(within(table).getByRole('link', { name: 'Customer One' })).toHaveAttribute('href', expect.stringMatching(/^#\/sales\/customers\/11/))
    expect(within(table).getByText('Payment Overdue')).toHaveClass('status-bad')
    expect(within(table).getByText('Customer has not paid by the due date.')).toBeInTheDocument()
    expect(within(screen.getByRole('navigation', { name: 'Parties pages' })).getByRole('link', { name: 'Payables' })).toHaveAttribute('href', expect.stringMatching(/^#\/parties\/payables/))
  })

  it('uses the legacy aggregate status field when payment_status is absent', async () => {
    const legacyAgeing = {
      ...ageingFound,
      rows: ageingFound.rows.map(({ payment_status: _paymentStatus, ...row }) => row),
      total: (({ payment_status: _paymentStatus, ...row }) => row)(ageingFound.total),
    }
    stubApi({ '/api/v1/companies': companies, '/api/v1/periods': periods, '/api/v1/ageing/customers': legacyAgeing })
    renderApp('#/parties/receivables')
    const table = await screen.findByRole('table', { name: 'Customers by ageing' })
    expect(within(table).getByText('Payment Overdue')).toBeInTheDocument()
    expect(within(table).queryByText('Payment Pending')).toBeNull()
    expect(within(table).getByText('No bill details')).toBeInTheDocument()
  })

  it('shows direction-aware statuses and meanings for supplier payables', async () => {
    const vendors = {
      ...ageingFound,
      kind: 'vendors',
      rows: [
        { ...ageingRow(21, 'Supplier Credit', '-100', '0', '100', '-200'), status: 'overdue', payment_status: 'overdue' },
        { ...ageingRow(22, 'Overdue Supplier', '100', '0', '100', '0'), payment_status: 'overdue' },
        { ...ageingRow(23, 'Pending Supplier', '200', '200', '0', '0'), payment_status: 'pending' },
        { ...ageingRow(24, 'Mixed Supplier', '150', '50', '100', '0'), payment_status: 'mixed' },
      ],
    }
    stubApi({ '/api/v1/companies': companies, '/api/v1/periods': periods, '/api/v1/ageing/vendors': vendors })
    renderApp('#/parties/payables')

    const table = await screen.findByRole('table', { name: 'Vendors by ageing' })
    expect(within(table).getByText('Supplier Advance')).toHaveClass('status-good')
    expect(within(table).getByText('Your company has paid the supplier extra. This amount is available as credit.')).toBeInTheDocument()
    expect(within(table).getByText('Payment to Supplier Overdue')).toHaveClass('status-bad')
    expect(within(table).getByText('Payment to Supplier Pending')).toBeInTheDocument()
    expect(within(table).getByText('Multiple bill statuses')).toBeInTheDocument()
  })
})

describe('the Purchases dashboard', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('shows the purchase side with the vendors and the mix by voucher type', async () => {
    stubApi({ '/api/v1/companies': companies, '/api/v1/periods': periods, '/api/v1/purchases/dashboard': sales })
    renderApp('#/purchases/dashboard?vtype=Purchase')
    const net = await screen.findByRole('region', { name: 'Net purchases' })
    expect(net).toHaveTextContent('₹48.20 Cr')
    expect(screen.getByRole('region', { name: 'Purchase returns' })).toBeInTheDocument()
    const request = requests.filter((r) => r.includes('/purchases/dashboard')).pop() ?? ''
    expect(request).toContain('voucher_type=Purchase')
    const top = screen.getByRole('table', { name: 'Top vendors' })
    expect(within(top).getByRole('link', { name: 'Customer One' })).toHaveAttribute('href', expect.stringMatching(/^#\/purchases\/vendors\/11/))
    const mix = screen.getByRole('group', { name: 'Net purchases by voucher type' })
    expect(within(mix).getByRole('link', { name: 'Sales' })).toHaveAttribute('href', expect.stringMatching(/^#\/purchases\/register\?.*vtype=Sales/))
    expect(within(screen.getByRole('navigation', { name: 'Purchases pages' })).getByRole('link', { name: 'Purchases dashboard' })).toHaveAttribute('aria-current', 'page')
  })
})

describe('the Sales dashboard', () => {
  beforeEach(() => {
    window.localStorage.clear()
    stubApi({ '/api/v1/companies': companies, '/api/v1/periods': periods, '/api/v1/sales/dashboard': sales })
  })
  afterEach(() => vi.unstubAllGlobals())

  const lastRequest = () => requests.filter((r) => r.includes('/sales/dashboard')).pop() ?? ''

  it('shows the key figures with the change against last year', async () => {
    renderApp('#/sales/dashboard')
    const net = await screen.findByRole('region', { name: 'Net sales' })
    expect(net).toHaveTextContent('₹48.20 Cr')
    expect(net).toHaveTextContent('▲ 12% vs last year')
    expect(screen.getByRole('region', { name: 'Invoices' })).toHaveTextContent('120')
    expect(within(screen.getByRole('region', { name: 'Sales returns' })).getByText(/▲ 25%/)).toHaveClass('change', 'neutral')
    expect(document.querySelector('.header-crumbs')).toHaveTextContent('Sales/Sales dashboard')
    expect(net).toHaveClass('kpi-card')
    // The mix by channel, each opening its register.
    const mix = screen.getByRole('group', { name: 'Net sales by channel' })
    expect(within(mix).getByRole('link', { name: 'Online Sales' })).toHaveAttribute('href', expect.stringMatching(/^#\/sales\/register\?.*channel=Online\+Sales/))
    expect(within(mix).getByText('20.7%')).toBeInTheDocument()
    // The top customers with their status.
    const top = screen.getByRole('table', { name: 'Top customers' })
    expect(within(top).getByText('Payment Overdue')).toHaveClass('status-bad')
    expect(within(top).getByText('Fully Settled')).toHaveClass('status-good')
    expect(within(top).getByText('Customer has not paid by the due date.')).toBeInTheDocument()
  })

  it('uses the legacy party status field when payment_status is absent', async () => {
    const legacySales = {
      ...sales,
      top_customers: sales.top_customers.map(({ payment_status: _paymentStatus, ...party }) => party),
    }
    stubApi({ '/api/v1/companies': companies, '/api/v1/periods': periods, '/api/v1/sales/dashboard': legacySales })
    renderApp('#/sales/dashboard')
    const table = await screen.findByRole('table', { name: 'Top customers' })
    expect(within(table).getByText('Payment Overdue')).toBeInTheDocument()
    expect(within(table).getByText('Fully Settled')).toBeInTheDocument()
  })

  it('classifies customer balances by normalized direction and requires bill details for overdue', async () => {
    const [overdueCustomer, settledCustomer] = sales.top_customers
    const { payment_status: _paymentStatus, ...customerWithoutBillStatus } = settledCustomer
    const response = {
      ...sales,
      top_customers: [
        { ...overdueCustomer, balance: '-100.00', overdue: '75.00', status: 'overdue', payment_status: 'overdue' },
        { ...settledCustomer, balance: '0.00', status: 'overdue', payment_status: 'overdue' },
        { ...overdueCustomer, party_id: 13, name: 'Customer Three', balance: '100.00', status: 'current', payment_status: 'mixed' },
        { ...customerWithoutBillStatus, party_id: 14, name: 'Customer Four', balance: '100.00', status: 'current' },
      ],
    }
    stubApi({ '/api/v1/companies': companies, '/api/v1/periods': periods, '/api/v1/sales/dashboard': response })
    renderApp('#/sales/dashboard')

    const table = await screen.findByRole('table', { name: 'Top customers' })
    expect(within(table).getByText('Customer Advance')).toBeInTheDocument()
    expect(within(table).getByText('Customer has paid extra. This amount is available as credit.')).toBeInTheDocument()
    expect(within(table).getByText('Fully Settled')).toBeInTheDocument()
    expect(within(table).getByText('Multiple bill statuses')).toBeInTheDocument()
    expect(within(table).getByText('No bill details')).toBeInTheDocument()
    expect(within(table).queryByText('Payment Overdue')).toBeNull()
  })

  it('shows direction-aware supplier statuses and meanings in Purchases', async () => {
    const [overdueSupplier, pendingSupplier] = sales.top_customers
    const response = {
      ...sales,
      top_customers: [
        { ...overdueSupplier, balance: '-100.00', status: 'overdue', payment_status: 'overdue' },
        { ...overdueSupplier, party_id: 13, name: 'Supplier Two', balance: '100.00', status: 'overdue', payment_status: 'overdue' },
        { ...pendingSupplier, party_id: 14, name: 'Supplier Three', balance: '200.00', status: 'current', payment_status: 'pending' },
      ],
    }
    stubApi({ '/api/v1/companies': companies, '/api/v1/periods': periods, '/api/v1/purchases/dashboard': response })
    renderApp('#/purchases/dashboard')

    const table = await screen.findByRole('table', { name: 'Top vendors' })
    expect(within(table).getByText('Supplier Advance')).toHaveClass('status-good')
    expect(within(table).getByText('Your company has paid the supplier extra. This amount is available as credit.')).toBeInTheDocument()
    expect(within(table).getByText('Payment to Supplier Overdue')).toHaveClass('status-bad')
    expect(within(table).getByText('Your company has not paid the supplier by the due date.')).toBeInTheDocument()
    expect(within(table).getByText('Payment to Supplier Pending')).toBeInTheDocument()
    expect(within(table).getByText('Your company needs to pay the supplier, but the due date has not passed.')).toBeInTheDocument()
  })

  it('uses configured company labels in selectors, tables and the branch chart', async () => {
    const mapped = companies.map((company) => ({
      ...company,
      display_name: company.id === 3 ? 'North' : 'South',
    }))
    stubApi({ '/api/v1/companies': mapped, '/api/v1/periods': periods, '/api/v1/sales/dashboard': sales })
    renderApp('#/sales/dashboard?company=3&company=4')
    await screen.findByRole('region', { name: 'Net sales' })
    expect(screen.getByRole('group', { name: 'Companies' })).toHaveTextContent('North')
    expect(screen.getByRole('group', { name: 'Companies' })).toHaveTextContent('South')
    expect(screen.getByRole('region', { name: 'Monthly sales by branch' })).toHaveTextContent(
      'Each series represents a selected company',
    )
    expect(within(screen.getByRole('table', { name: 'Top customers' })).getByText('South')).toBeInTheDocument()
  })

  it('applies the customer and channel facets, and no others', async () => {
    renderApp('#/sales/dashboard?customer=Customer%20One&channel=Sales')
    await screen.findByRole('region', { name: 'Net sales' })
    expect(lastRequest()).toContain('customer=Customer+One')
    expect(lastRequest()).toContain('channel=Sales')
    expect(screen.queryByRole('combobox', { name: 'Voucher type' })).toBeNull() // not a facet of sales
  })

  it('lists the months, customers and invoices, each linking deeper where a page exists', async () => {
    renderApp('#/sales/dashboard?company=3&company=4')
    const months = await screen.findByRole('table', { name: 'Sales by month' })
    // A month opens its register.
    expect(within(months).getByRole('link', { name: 'Apr-2026' }).getAttribute('href')).toMatch(/^#\/sales\/register\?.*month=2026-04/)
    expect(within(months).getByText('Total')).toBeInTheDocument()
    const customers = screen.getByRole('table', { name: 'Top customers' })
    // A customer opens their page.
    expect(within(customers).getByRole('link', { name: 'Customer One' }).getAttribute('href')).toMatch(/^#\/sales\/customers\/11\?/)
    expect(within(customers).getByText('Beta')).toBeInTheDocument() // combined: the company shown
    const invoices = screen.getByRole('table', { name: 'Largest invoices' })
    expect(within(invoices).queryByRole('link', { name: 'S-17' })).toBeNull() // no voucher page yet
    expect(within(invoices).getByText('04-May-2026')).toBeInTheDocument()
  })

  it('filters a table', async () => {
    renderApp('#/sales/dashboard')
    const invoices = await screen.findByRole('table', { name: 'Largest invoices' })
    fireEvent.change(screen.getByRole('searchbox', { name: 'Filter Largest invoices' }), { target: { value: 'online' } })
    expect(within(invoices).queryByText('S-17')).toBeNull()
    expect(within(invoices).getByText('S-3')).toBeInTheDocument()
  })

  it('explains itself on request, and each card on hover', async () => {
    renderApp('#/sales/dashboard')
    const net = await screen.findByRole('region', { name: 'Net sales' })
    fireEvent.mouseEnter(within(net).getByText('Net sales'))
    expect(await screen.findByText(/Sales after returns and adjustments.*= Gross sales \+ sales returns.*\(F-SAL-004\)/)).toBeInTheDocument()
    fireEvent.mouseEnter(within(screen.getByRole('region', { name: 'Average invoice' })).getByText('Average invoice'))
    expect(await screen.findByText(/Gross sales per invoice\. = Gross ÷ Invoices \(F-SAL-006\)/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'What is this?' }))
    expect(await screen.findByText(/Sales of the companies, period, customers and channels you chose/)).toBeInTheDocument()
  })

  it('explains a status on hover', async () => {
    renderApp('#/sales/dashboard')
    const top = await screen.findByRole('table', { name: 'Top customers' })
    fireEvent.mouseEnter(within(top).getByText('Payment Overdue'))
    expect(await screen.findByText('Customer has not paid by the due date.')).toBeInTheDocument()
  })

})

const row = (id: number, date: string, type: string, debit: string | null, credit: string | null, value: string) => ({
  voucher_id: id,
  company: 3,
  date,
  voucher_type: type,
  is_return: credit !== null,
  number: `V-${id}`,
  ledger_id: 40 + id,
  particulars: 'Customer One',
  party_id: 11,
  party: 'Customer One',
  debit,
  credit,
  side_value: value,
  narration: id === 1 ? 'First sale' : null,
  reference: id === 1 ? 'SUP-INV-4471' : null,
  instrument_number: id === 1 ? '000451' : null,
  transaction_reference: id === 1 ? 'UTR20260902000017' : null,
})
const salesRegister: RegisterOut = {
  side: 'sales',
  companies: [3],
  combined: false,
  period: { start: '2026-04-01', end: '2026-09-30', months: [] },
  rows: [
    row(1, '2026-04-02', 'Sales', '118000', null, '100000'),
    row(2, '2026-04-20', 'Credit Note', null, '11800', '-10000'),
    row(3, '2026-05-05', 'Sales', '59000', null, '50000'),
  ],
  truncated: false,
}

describe('the Sales and Purchase registers', () => {
  beforeEach(() => {
    window.localStorage.clear()
    stubApi({
      '/api/v1/companies': [companies[0]],
      '/api/v1/periods': periods,
      '/api/v1/registers/sales': salesRegister,
      '/api/v1/registers/purchases': { ...salesRegister, side: 'purchases', rows: [], truncated: true },
    })
  })
  afterEach(() => vi.unstubAllGlobals())

  it('lists the vouchers Day Book style, by month with subtotals and the grand total', async () => {
    renderApp('#/sales/register')
    const table = await screen.findByRole('table', { name: 'Sales register' })
    const headers = within(table).getAllByRole('columnheader').map((h) => h.textContent)
    expect(headers).toEqual(['Date', 'Particulars', 'Vch Type', 'Vch No.', 'Debit', 'Credit', 'Narration'])
    expect(within(table).getByText('Month: Apr-2026 (2)')).toBeInTheDocument()
    expect(within(table).getByText('Month: May-2026 (1)')).toBeInTheDocument()
    const total = within(table).getByText('Grand total').closest('tr') as HTMLElement
    expect(total).toHaveTextContent('₹1,77,000.00')
    expect(total).toHaveTextContent('₹11,800.00')
    expect(within(table).getByText('First sale')).toBeInTheDocument()
    expect(document.querySelector('.header-crumbs')).toHaveTextContent('Sales/Sales register')
  })

  it('asks for the customer and channel facets by name', async () => {
    renderApp('#/sales/register?customer=Customer%20One&channel=Sales')
    await screen.findByRole('table', { name: 'Sales register' })
    const asked = requests.filter((r) => r.includes('/registers/sales')).pop() ?? ''
    expect(asked).toContain('party=Customer+One')
    expect(asked).toContain('voucher_type=Sales')
  })

  it('links a customer to their page', async () => {
    renderApp('#/sales/register')
    const table = await screen.findByRole('table', { name: 'Sales register' })
    const link = within(table).getAllByRole('link', { name: 'Customer One' })[0]
    expect(link.getAttribute('href')).toMatch(/^#\/sales\/customers\/11/)
    expect(within(table).queryByRole('link', { name: 'V-1' })).toBeNull() // no voucher page yet
  })

  it('offers the reference, cheque or transfer number and UTR as columns', async () => {
    renderApp('#/sales/register')
    const table = await screen.findByRole('table', { name: 'Sales register' })
    expect(within(table).queryByText('SUP-INV-4471')).toBeNull() // hidden until chosen
    fireEvent.click(screen.getByRole('button', { name: 'Columns ▾' }))
    fireEvent.click(await screen.findByLabelText('Reference'))
    fireEvent.click(await screen.findByLabelText('Cheque / transfer no.'))
    fireEvent.click(await screen.findByLabelText('UTR'))
    expect(await within(table).findByText('SUP-INV-4471')).toBeInTheDocument()
    expect(within(table).getByText('000451')).toBeInTheDocument()
    expect(within(table).getByText('UTR20260902000017')).toBeInTheDocument()
  })

  it('says when a register was cut short, and explains itself', async () => {
    renderApp('#/purchases/register')
    expect(await screen.findByText(/Only the first 0 vouchers are shown/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'What is this?' }))
    expect(await screen.findByText(/Debit Note Register/)).toBeInTheDocument()
    expect(screen.queryByRole('combobox', { name: 'Customer' })).toBeNull() // purchases take voucher types only
  })
})

const month = (m: string, net: string, closing: string) => ({ month: m, gross: net, returns: '0', other: '0', net, invoices: 2, closing })
const monthlySales: MonthlyOut = {
  side: 'sales',
  companies: [3],
  combined: false,
  period: { start: '2026-04-01', end: '2026-05-31', months: ['2026-04-01', '2026-05-01'] },
  months: [month('2026-04-01', '100000', '100000'), month('2026-05-01', '50000', '150000')],
}
const channelsFound: ChannelsOut = {
  companies: [3],
  combined: false,
  period: { start: '2026-04-01', end: '2026-05-31', months: ['2026-04-01', '2026-05-01'] },
  channels: [
    {
      name: 'Online Sales',
      months: [
        { month: '2026-04-01', net: '90000' },
        { month: '2026-05-01', net: '10000' },
      ],
      gross: '100000',
      returns: '0',
      other: '0',
      net: '100000',
      invoices: 3,
      share_pct: '66.7',
    },
    {
      name: 'Sales',
      months: [
        { month: '2026-04-01', net: '10000' },
        { month: '2026-05-01', net: '40000' },
      ],
      gross: '50000',
      returns: '0',
      other: '0',
      net: '50000',
      invoices: 1,
      share_pct: '33.3',
    },
  ],
}

describe('monthly sales and purchases, and sales by channel', () => {
  beforeEach(() => {
    window.localStorage.clear()
    stubApi({
      '/api/v1/companies': [companies[0]],
      '/api/v1/periods': periods,
      '/api/v1/monthly/sales': monthlySales,
      '/api/v1/monthly/purchases': { ...monthlySales, side: 'purchases' },
      '/api/v1/sales/channels': channelsFound,
    })
  })
  afterEach(() => vi.unstubAllGlobals())

  it('shows each month with its closing balance, without adding up the closing balances', async () => {
    renderApp('#/sales/monthly')
    const table = await screen.findByRole('table', { name: 'Monthly sales' })
    expect(within(table).getByRole('link', { name: 'Apr-2026' }).getAttribute('href')).toMatch(/^#\/sales\/register\?.*month=2026-04/)
    const total = within(table).getByText('Total').closest('tr') as HTMLElement
    expect(total).toHaveTextContent('₹1,50,000.00') // net
    expect(total.textContent?.match(/₹1,50,000\.00/g)).toHaveLength(2) // net and gross; no closing total
    fireEvent.click(screen.getByRole('button', { name: 'What is this?' }))
    expect(await screen.findByText(/financial year to the month/)).toBeInTheDocument()
  })

  it('has monthly purchases opening the purchase register', async () => {
    renderApp('#/purchases/monthly')
    const table = await screen.findByRole('table', { name: 'Monthly purchases' })
    expect(within(table).getByRole('link', { name: 'May-2026' }).getAttribute('href')).toMatch(/^#\/purchases\/register\?.*month=2026-05/)
    expect(document.querySelector('.header-crumbs')).toHaveTextContent('Purchases/Monthly purchases')
  })

  it('lists the channels with their months, each opening the register filtered to it', async () => {
    renderApp('#/sales/channels')
    const table = await screen.findByRole('table', { name: 'Sales by channel' })
    expect(within(table).getByRole('link', { name: 'Online Sales' }).getAttribute('href')).toContain('channel=Online+Sales')
    expect(within(table).getByText('66.7%')).toBeInTheDocument()
    const april = within(table).getAllByRole('link', { name: '₹90,000.00' })[0]
    expect(april.getAttribute('href')).toMatch(/channel=Online\+Sales.*month=2026-04|month=2026-04.*channel=Online\+Sales/)
  })
})

const partiesFound: PartiesOut = {
  kind: 'customers',
  companies: [3],
  combined: false,
  period: { start: '2026-04-01', end: '2026-09-30', months: [] },
  parties: [
    { party_id: 11, name: 'Customer One', companies: [3], balance: '1161000', net: '18400000', invoices: 214, last_invoice: '2026-09-28' },
    { party_id: 12, name: 'Customer Two', companies: [3], balance: '0', net: '500000', invoices: 3, last_invoice: null },
  ],
}
const invoice = (id: number, status: 'paid' | 'due' | 'overdue' | 'advance' | 'no_bill', days: number | null) => {
  const payment_status: PartyInvoiceOut['payment_status'] =
    status === 'paid' ? 'settled' : status === 'due' ? 'pending' : status
  return {
    ...row(id, '2026-08-27', 'Sales', '312750', null, '265000'),
    status,
    payment_status,
    days,
  }
}
const partyFound: PartyOut = {
  kind: 'customers',
  party_id: 11,
  name: 'Customer One',
  companies: [3],
  group_path: ['Sundry Debtors', 'Online customers'],
  credit_days: 30,
  main_channel: 'Online Sales',
  period: { start: '2026-04-01', end: '2026-09-30', months: [] },
  compared_with: null,
  balance: '1161000',
  overdue: '313000',
  bills_cover: '1000000',
  net: { value: '18400000', before: null, change_pct: null },
  invoices: { value: '214', before: null, change_pct: null },
  settled: '900000',
  days_to_pay: '38',
  invoices_list: [invoice(1, 'overdue', 64), invoice(3, 'paid', null)],
  invoices_truncated: false,
  settlements: [{ voucher_id: 9, company: 3, date: '2026-09-02', voucher_type: 'Receipt', number: 'R-4', amount: '900000', narration: null }],
  statement_opening: '200000',
  statement: [
    { voucher_id: 1, company: 3, date: '2026-08-27', voucher_type: 'Sales', number: 'V-1', particulars: 'Sales', debit: '1861000', credit: null, balance: '2061000', narration: null },
    { voucher_id: 9, company: 3, date: '2026-09-02', voucher_type: 'Receipt', number: 'R-4', particulars: 'Bank', debit: null, credit: '900000', balance: '1161000', narration: null },
  ],
  statement_truncated: false,
  bills: [{ company: 3, name: 'V-1', date: '2026-07-27', due: '2026-08-26', amount: '313000', overdue_days: 35, payment_status: 'overdue' }],
  monthly: [{ month: '2026-08-01', net: '18400000', invoices: 214, settled: '900000' }],
}

describe('the customers and their pages', () => {
  beforeEach(() => {
    window.localStorage.clear()
    stubApi({
      '/api/v1/companies': [companies[0]],
      '/api/v1/periods': periods,
      '/api/v1/parties/customers': partiesFound,
      '/api/v1/parties/customers/11': partyFound,
      '/api/v1/parties/vendors': { ...partiesFound, kind: 'vendors', parties: [] },
    })
  })
  afterEach(() => vi.unstubAllGlobals())

  it('lists the customers, each opening their page', async () => {
    renderApp('#/sales/customers')
    const table = await screen.findByRole('table', { name: 'Customers' })
    expect(within(table).getByRole('link', { name: 'Customer One' }).getAttribute('href')).toMatch(/^#\/sales\/customers\/11/)
    expect(within(table).getAllByText('₹11,61,000.00')).toHaveLength(2) // the row and the total
    expect(document.querySelector('.header-crumbs')).toHaveTextContent('Sales/Customers')
  })

  it('shows a customer with key figures, bills and their status, and breadcrumbs back', async () => {
    renderApp('#/sales/customers/11')
    expect(await within(screen.getByRole('region', { name: 'Page' })).findByRole('heading', { level: 1, name: 'Customer One' })).toBeInTheDocument()
    expect(screen.getByText('Customer · Sundry Debtors · Online customers')).toBeInTheDocument()
    expect(screen.getByText(/Main channel: Online Sales · Companies: Alpha · Credit period 30 days/)).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Overdue' })).toHaveTextContent('₹3.1 L')
    expect(screen.getByRole('region', { name: 'Average days to pay' })).toHaveTextContent('38 days')
    expect(screen.getByText('Payment Overdue (64 days)')).toBeInTheDocument()
    expect(screen.getByText('Fully Settled')).toBeInTheDocument()
    const crumbs = document.querySelector('.header-crumbs') as HTMLElement
    expect(crumbs).toHaveTextContent('Sales/Customers/Customer One')
    expect(within(crumbs).getByRole('link', { name: 'Customers' }).getAttribute('href')).toMatch(/^#\/sales\/customers(\?|$)/)
  })

  it('uses legacy invoice status and bill values when payment_status is absent', async () => {
    const legacyParty = {
      ...partyFound,
      invoices_list: partyFound.invoices_list.map(({ payment_status: _paymentStatus, ...invoiceRow }) => invoiceRow),
      bills: partyFound.bills.map(({ payment_status: _paymentStatus, ...bill }) => bill),
    }
    stubApi({
      '/api/v1/companies': [companies[0]],
      '/api/v1/periods': periods,
      '/api/v1/parties/customers': partiesFound,
      '/api/v1/parties/customers/11': legacyParty,
      '/api/v1/parties/vendors': { ...partiesFound, kind: 'vendors', parties: [] },
    })
    renderApp('#/sales/customers/11')
    const invoices = await screen.findByRole('table', { name: 'Invoices' })
    expect(within(invoices).getByText('Payment Overdue (64 days)')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('tab', { name: 'Outstanding bills' }))
    const bills = await screen.findByRole('table', { name: 'Outstanding bills' })
    expect(within(bills).getByText('Payment Overdue')).toBeInTheDocument()
    expect(within(bills).getByText('Customer has not paid by the due date.')).toBeInTheDocument()
  })

  it('opens the ledger statement with the running balance, and says when bills cover less', async () => {
    renderApp('#/sales/customers/11?tab=statement')
    const table = await screen.findByRole('table', { name: 'Ledger statement' })
    expect(within(table).getByText('₹11,61,000.00 Dr')).toBeInTheDocument()
    expect(screen.getByText(/Opening balance on 01-Apr-2026: ₹2,00,000.00 Dr/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Outstanding bills' }))
    expect(await screen.findByText(/The bills add up to ₹10,00,000.00 of the ₹11,61,000.00 balance due/)).toBeInTheDocument()
    expect(window.location.hash).toContain('tab=bills')
  })

  it('says so for a party that is not there', async () => {
    renderApp('#/sales/customers/77')
    expect(await screen.findByText("The customer couldn't be loaded.")).toBeInTheDocument()
  })
})

const centresFound: CentresOut = {
  companies: [3],
  combined: false,
  period: { start: '2026-08-01', end: '2026-09-30', months: [] },
  centres: [
    {
      centre_id: 21, name: 'Head Office', category: 'Primary Cost Category', parent: null, companies: [3],
      months: [{ month: '2026-08-01', amount: '1000' }, { month: '2026-09-01', amount: '6200' }], total: '7200', allocations: 3,
    },
    {
      centre_id: 23, name: 'Alpha Phase 1', category: 'Projects', parent: 'Project Alpha', companies: [3],
      months: [{ month: '2026-08-01', amount: '0' }, { month: '2026-09-01', amount: '2500' }], total: '2500', allocations: 1,
    },
  ],
}

const centreFound: CentrePageOut = {
  centre: centresFound.centres[0],
  period: centresFound.period,
  allocations: [
    { company: 3, date: '2026-09-01', voucher_id: 31, voucher_number: 'CC-2', voucher_type: 'Payment', ledger: 'Electricity', category: 'Primary Cost Category', amount: '4000' },
    { company: 3, date: '2026-09-02', voucher_id: 32, voucher_number: 'PI-9', voucher_type: 'Purchase', ledger: 'Purchases', category: 'Primary Cost Category', amount: '200' },
  ],
  truncated: false,
}

describe('the cost centres', () => {
  beforeEach(() => {
    window.localStorage.clear()
    stubApi({
      '/api/v1/companies': [companies[0]],
      '/api/v1/periods': periods,
      '/api/v1/cost-centres': centresFound,
      '/api/v1/cost-centres/21': centreFound,
    })
  })
  afterEach(() => vi.unstubAllGlobals())

  it('lists each cost centre by month with its category and where it sits, each opening its page', async () => {
    renderApp('#/pnl/cost-centres')
    const table = await screen.findByRole('table', { name: 'Cost centres' })
    const headers = within(table).getAllByRole('columnheader').map((h) => h.textContent)
    expect(headers).toEqual(['Cost centre', 'Cost category', 'Under', 'Aug-2026', 'Sep-2026', 'Allocated', 'Allocations'])
    const alpha = within(table).getByRole('link', { name: 'Alpha Phase 1' })
    expect(alpha.closest('tr')).toHaveTextContent('Project Alpha')
    expect(within(table).getByRole('link', { name: 'Head Office' }).getAttribute('href')).toMatch(/^#\/pnl\/cost-centres\/21/)
    expect(within(table).getByText('Total').closest('tr')).toHaveTextContent('₹9,700.00')
    expect(document.querySelector('.header-crumbs')).toHaveTextContent('P&L & KPIs/Cost centres')
  })

  it('opens a cost centre with its allocations voucher by voucher, and breadcrumbs back', async () => {
    renderApp('#/pnl/cost-centres/21')
    const table = await screen.findByRole('table', { name: 'Allocations' })
    expect(within(table).getByText('Electricity').closest('tr')).toHaveTextContent('₹4,000.00')
    expect(within(table).getByText('Total').closest('tr')).toHaveTextContent('₹4,200.00')
    expect(screen.getByText('Primary Cost Category · 3 allocations')).toBeInTheDocument()
    const crumbs = document.querySelector('.header-crumbs') as HTMLElement
    expect(crumbs).toHaveTextContent('P&L & KPIs/Cost centres/Head Office')
    expect(within(crumbs).getByRole('link', { name: 'Cost centres' }).getAttribute('href')).toMatch(/^#\/pnl\/cost-centres(\?|$)/)
  })

  it('says so for a cost centre that is not there', async () => {
    renderApp('#/pnl/cost-centres/77')
    expect(await screen.findByText("The cost centre couldn't be loaded.")).toBeInTheDocument()
  })

  it('is a page of the P&L & KPIs module', async () => {
    renderApp('#/pnl/profit-loss')
    expect((await screen.findByRole('link', { name: 'Cost centres' })).getAttribute('href')).toMatch(/^#\/pnl\/cost-centres/)
  })
})
