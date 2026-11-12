import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
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
  StockGodownsOut,
  VoucherOut,
  DatasetInfo,
  DatasetResult,
  StockItemPageOut,
  StockOut,
  TransactionsOut,
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

afterEach(() => window.localStorage.removeItem('ledgerbridge.amounts')) // the Amounts setting stays per test

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

/** Amounts in full (the Amounts setting), for tests of exact table figures. */
function fullAmounts() {
  window.localStorage.setItem('ledgerbridge.amounts', 'full')
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

  it('shows amounts in lakhs with the full amount on hover, or in full when chosen (F-FMT-001)', async () => {
    window.localStorage.removeItem('ledgerbridge.amounts')
    renderApp('#/overview/dashboard')
    const net = await screen.findByRole('region', { name: 'Net sales' })
    fireEvent.mouseEnter(within(net).getByText('₹4,820.00 L'))
    expect(await screen.findByText('₹48,20,00,000.00')).toBeInTheDocument()
    const top = screen.getByRole('table', { name: 'Top customers by net sales' })
    expect(within(top).getByText('₹11.61 L')).toBeInTheDocument()
    fireEvent.mouseDown(screen.getByRole('combobox', { name: 'Amounts' }))
    fireEvent.click((await screen.findAllByText('Full amounts')).slice(-1)[0])
    expect(await within(net).findByText('₹48,20,00,000.00')).toBeInTheDocument()
    expect(within(top).getByText('₹11,61,000.00')).toBeInTheDocument()
    expect(window.localStorage.getItem('ledgerbridge.amounts')).toBe('full') // remembered
  })

  it('keeps the Overview\'s tables inside their cards: long text wraps, a wide table scrolls', async () => {
    renderApp('#/overview/dashboard')
    const top = await screen.findByRole('table', { name: 'Top customers by net sales' })
    expect(top.parentElement).toHaveClass('report-table-wrap')
    expect(screen.getByRole('table', { name: 'Profit & Loss against last year' }).parentElement).toHaveClass('report-table-wrap')
    const meaning = within(top).getAllByRole('cell').find((c) => c.textContent?.startsWith('Customer has not paid'))
    expect(meaning).toHaveClass('wrap')
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
    expect(within(net).getByText('₹4,820.00 L')).toBeInTheDocument()
    expect(within(net).getByText('▲ 12% vs last year')).toHaveClass('good')
    expect(net).toHaveClass('kpi-card')
    const gross = screen.getByRole('region', { name: 'Gross profit' })
    expect(within(gross).getByText('₹1,510.00 L')).toBeInTheDocument()
    expect(within(gross).getByText('Gross margin 31.3%')).toBeInTheDocument()
    expect(within(screen.getByRole('region', { name: 'Net profit' })).getByText('Net margin 12.9%')).toBeInTheDocument()
    expect(within(screen.getByRole('region', { name: 'Cash & bank' })).getByText('₹115.00 L')).toBeInTheDocument()
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
    expect(within(table).getByText('3,822.90')).toBeInTheDocument() // ₹ lakh
    expect(within(table).getByText('-40.90').closest('td')).toHaveClass('negative') // a loss in crimson
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
  buckets: { not_due: notDue, days_1_30: '0', days_31_60: '0', days_61_90: '0', days_91_180: over90, over_180: '0' },
  overdue: over90,
  over_90: over90,
  uncovered,
  not_in_bills: { total: uncovered, on_account: uncovered, opening_difference: '0', revaluation: '0', other: '0' },
  status: over90 === '0' ? ('current' as const) : ('overdue' as const),
  payment_status: balance.startsWith('-') ? 'advance' : balance === '0' ? 'settled' : over90 === '0' ? 'pending' : 'overdue',
})
const ageingFound = {
  kind: 'customers',
  companies: [3, 4],
  combined: true,
  as_of: '2026-09-30',
  basis: 'due_date',
  rows: [ageingRow(11, 'Customer One', '1161000', '600000', '400000', '161000'), ageingRow(12, 'Customer Two', '200000', '200000', '0', '0')],
  total: { ...ageingRow(0, 'Total', '1361000', '800000', '400000', '161000') },
  bills: [
    { party_id: 11, party: 'Customer One', bill: 'S-1', bill_date: '2026-04-01', due_date: '2026-05-01', days: 152, overdue_days: 152, bucket: 'days_91_180', amount: '400000', voucher_id: 7 },
    { party_id: 11, party: 'Customer One', bill: 'OB-1', bill_date: '2026-03-01', due_date: '2026-10-15', days: -15, overdue_days: 0, bucket: 'not_due', amount: '600000', voucher_id: null },
  ],
  days_to_pay: '45',
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
    { key: 'current_ratio', label: 'Current ratio', unit: 'times' as const, formula_id: 'F-RAT-008', value: '1.82', before: '1.75', change: '0.07' },
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
    expect(await screen.findByRole('region', { name: 'Money in' })).toHaveTextContent('₹9.00 L')
    expect(screen.getByRole('region', { name: 'Money out' })).toHaveTextContent('₹7.00 L')
    expect(screen.getByRole('region', { name: 'Cash & bank at the end' })).toHaveTextContent('₹12.00 L')
    const table = screen.getByRole('table', { name: 'Cash movement by what it was for' })
    expect(within(table).getByText('Suppliers').closest('tr')).toHaveTextContent('-₹7.00 L')
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
    expect(within(table).getByText('Total assets').closest('tr')).toHaveTextContent('₹6,280.00 L')
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

describe('the ratio tiles show what they are worked out from', () => {
  afterEach(() => vi.unstubAllGlobals())

  const basis = {
    current_assets: '79278', current_liabilities: '38489', borrowings: '12000', stock: '5580', equity: '47889',
    asset_parts: [
      { key: 'cash', label: 'Cash in hand', amount: '26059' },
      { key: 'supplier_advances', label: 'Advances to suppliers (creditors in debit)', amount: '700' },
      { key: 'stock', label: 'Closing stock', amount: '5580' },
    ],
    liability_parts: [
      { key: 'payables', label: 'Trade payables (creditors in credit)', amount: '7150' },
      { key: 'short_term_borrowings', label: 'Short-term borrowings (Bank OD, banks in credit, marked loans)', amount: '12000' },
    ],
    borrowing_parts: [{ key: 'short_term_borrowings', label: 'Short-term borrowings', amount: '12000' }],
    marked_short_term: 1,
    combined: true,
  }
  const withBasis = {
    ...sheetFound,
    ratios: [
      { key: 'current_ratio', label: 'Current ratio', unit: 'times' as const, formula_id: 'F-RAT-008', value: '2.06', before: null, change: null, basis },
      { key: 'debt_to_equity', label: 'Debt to equity', unit: 'times' as const, formula_id: 'F-RAT-010', value: '0.25', before: null, change: null, basis },
      ...sheetFound.ratios.filter((r) => r.key !== 'current_ratio'),
    ],
  }

  it('lists current assets and liabilities with their parts, the marked loans and the combination on hover', async () => {
    fullAmounts()
    stubApi({ '/api/v1/companies': companies, '/api/v1/periods': periods, '/api/v1/reports/balance-sheet': withBasis })
    renderApp('#/balance-sheet/statement')
    const tile = await screen.findByRole('listitem', { name: 'Current ratio' })
    expect(tile).toHaveAttribute('data-formula', 'F-RAT-008')
    const value = within(tile).getByText('2.06×')
    expect(value).toHaveAttribute('tabindex', '0') // reachable from the keyboard too
    fireEvent.mouseEnter(value)
    const shown = await screen.findByLabelText('How it is worked out')
    expect(shown).toHaveTextContent(/Current assets\s*₹79,278\.00/)
    expect(shown).toHaveTextContent(/Advances to suppliers \(creditors in debit\)\s*₹700\.00/)
    expect(shown).toHaveTextContent(/÷ Current liabilities\s*₹38,489\.00/)
    expect(shown).toHaveTextContent(/Short-term borrowings \(Bank OD, banks in credit, marked loans\)\s*₹12,000\.00/)
    expect(shown).toHaveTextContent('Includes 1 ledger marked as short-term.')
    expect(shown).toHaveTextContent('At 30-Sep-2026.')
    expect(shown).toHaveTextContent('Several companies combined, without inter-company eliminations.')
  })

  it('shows borrowings over equity for debt to equity', async () => {
    fullAmounts()
    stubApi({ '/api/v1/companies': companies, '/api/v1/periods': periods, '/api/v1/reports/balance-sheet': withBasis })
    renderApp('#/balance-sheet/statement')
    const tile = await screen.findByRole('listitem', { name: 'Debt to equity' })
    fireEvent.mouseEnter(within(tile).getByText('0.25×'))
    const shown = await screen.findByLabelText('How it is worked out')
    expect(shown).toHaveTextContent(/Borrowings\s*₹12,000\.00/)
    expect(shown).toHaveTextContent(/÷ Equity \(capital and profit\)\s*₹47,889\.00/)
  })
})

const voucherFound: VoucherOut = {
  voucher_id: 7, company: 3, date: '2026-04-01', voucher_type: 'Sales', number: 'S-1', party_id: 11, party: 'Customer One',
  reference: 'PO-9', narration: 'Two widgets', cancelled: false, optional: false, total_debit: '118000', total_credit: '118000',
  lines: [
    { line_no: 1, ledger_id: 5, ledger: 'Customer One', debit: '118000', credit: null, effective: true, instrument_number: null },
    { line_no: 2, ledger_id: 6, ledger: 'Sales - Goods', debit: null, credit: '100000', effective: true, instrument_number: null },
    { line_no: 3, ledger_id: 7, ledger: 'Output IGST', debit: null, credit: '18000', effective: true, instrument_number: null },
  ],
  bills: [{ ledger: 'Customer One', bill_type: 'new_ref', bill_name: 'S-1', bill_date: '2026-04-01', due_date: '2026-05-01', debit: '118000', credit: null }],
  stock: [{ line_no: 1, item_id: 41, item: 'Widget', godown: 'Main Location', other_godown: null, batch: null, quantity: '-2', rate: '50000', amount: '-100000' }],
}
const datasetsFound: DatasetInfo[] = [
  {
    key: 'voucher_lines', label: 'Voucher lines',
    dimensions: [{ key: 'date', label: 'Date', groupable: false }, { key: 'month', label: 'Month', groupable: true }, { key: 'ledger', label: 'Ledger', groupable: true }],
    measures: [{ key: 'debit', label: 'Debit', formula: 'F-TRN-001' }, { key: 'credit', label: 'Credit', formula: 'F-TRN-001' }, { key: 'voucher_count', label: 'Vouchers', formula: 'F-TBL-003' }],
    filters: [{ key: 'date_from', label: 'From', kind: 'date_from' }, { key: 'date_to', label: 'To', kind: 'date_to' }, { key: 'ledger', label: 'Ledger', kind: 'ids' }],
    default_columns: ['date', 'ledger'], default_measures: ['debit', 'credit'],
  },
  {
    key: 'inventory_lines', label: 'Inventory lines',
    dimensions: [{ key: 'item', label: 'Item', groupable: true }],
    measures: [{ key: 'quantity', label: 'Quantity', formula: 'F-STK-014' }],
    filters: [], default_columns: ['item'], default_measures: ['quantity'],
  },
]
const datasetResult: DatasetResult = {
  dataset: 'voucher_lines', group_by: [], columns: ['date', 'ledger'], measures: ['debit', 'credit'],
  rows: [{ keys: { date: { id: '2026-04-01', label: '01-Apr-2026' }, ledger: { id: 5, label: 'Customer One' } }, values: { debit: '118000', credit: '0' } }],
  subtotals: [], total: { debit: '118000', credit: '0' }, page: 1, page_size: 100, total_rows: 1,
}

describe('Receivables with ageing', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('shows the buckets as bars and every customer with their status, as at the period end', async () => {
    stubApi({ '/api/v1/companies': companies, '/api/v1/periods': periods, '/api/v1/ageing/customers': ageingFound })
    renderApp('#/parties/receivables')
    const due = await screen.findByRole('region', { name: 'Total outstanding' })
    expect(due).toHaveTextContent('₹13.61 L')
    expect(due).toHaveTextContent('= Sundry Debtors on the Balance Sheet')
    expect(screen.getByRole('region', { name: 'Over 90 days' })).toHaveTextContent('₹4.00 L')
    const bars = screen.getByRole('list', { name: 'Outstanding bills by bucket' })
    expect(within(bars).getByText('Not due').closest('.hbar')).toHaveTextContent('66.7%')
    expect(within(bars).getByText('91–180 days').closest('.hbar')).toHaveTextContent('33.3%')
    expect(within(bars).getByText('Over 180 days')).toBeInTheDocument()
    const table = screen.getByRole('table', { name: 'Customers by ageing' })
    expect(within(table).getByRole('link', { name: 'Customer One' })).toHaveAttribute('href', expect.stringMatching(/^#\/sales\/customers\/11/))
    expect(within(table).getByText('Payment Overdue')).toHaveClass('status-bad')
    expect(within(table).getByText('Customer has not paid by the due date.')).toBeInTheDocument()
    expect(within(screen.getByRole('navigation', { name: 'Parties pages' })).getByRole('link', { name: 'Payables' })).toHaveAttribute('href', expect.stringMatching(/^#\/parties\/payables/))
  })

  it('explains ageing, splits what is not in bills, opens the voucher of each bill and ages by bill date on request', async () => {
    stubApi({ '/api/v1/companies': companies, '/api/v1/periods': periods, '/api/v1/ageing/customers': ageingFound })
    renderApp('#/parties/receivables')
    const note = (await screen.findByText('How ageing is worked out')).closest('details') as HTMLDetailsElement
    expect(note.open).toBe(true)
    expect(note).toHaveTextContent('six groups: not due, 1–30, 31–60, 61–90, 91–180 and over 180 days')
    expect(note).toHaveTextContent("The total equals the Sundry Debtors balance on Tally's Balance Sheet")
    expect(await screen.findByRole('region', { name: 'Average days to pay' })).toHaveTextContent('45 days')
    const parts = screen.getByRole('table', { name: 'Not in bills' })
    expect(within(parts).getByText('On account').closest('tr')).toHaveTextContent('₹1.61 L')
    expect(within(parts).getByText('Exchange-rate revaluation')).toBeInTheDocument()
    expect(within(parts).getByText('Total not in bills').closest('tr')).toHaveTextContent('₹1.61 L')
    const bills = screen.getByRole('table', { name: 'Outstanding bills' })
    expect(within(bills).getByRole('link', { name: 'S-1' }).getAttribute('href')).toMatch(/^#\/books\/vouchers\/7/)
    expect(within(bills).queryByRole('link', { name: 'OB-1' })).toBeNull() // an opening bill has no voucher
    fireEvent.click(screen.getByRole('button', { name: 'Days since the bill date' }))
    await waitFor(() => expect(requests.some((r) => r.includes('/api/v1/ageing/customers') && r.includes('basis=bill_date'))).toBe(true))
    expect(window.location.hash).toContain('basis=bill_date')
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
    expect(net).toHaveTextContent('₹4,820.00 L')
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
    expect(net).toHaveTextContent('₹4,820.00 L')
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
    expect(within(invoices).getByRole('link', { name: 'S-17' }).getAttribute('href')).toMatch(/^#\/books\/vouchers\/\d+/) // opens the voucher
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
    fullAmounts()
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
    expect(within(table).getByRole('link', { name: 'V-1' }).getAttribute('href')).toMatch(/^#\/books\/vouchers\/1/) // opens the voucher
  })

  it('offers the reference and the cheque or transfer number as columns, never a UTR', async () => {
    renderApp('#/sales/register')
    const table = await screen.findByRole('table', { name: 'Sales register' })
    expect(within(table).queryByText('SUP-INV-4471')).toBeNull() // hidden until chosen
    fireEvent.click(screen.getByRole('button', { name: 'Columns ▾' }))
    fireEvent.click(await screen.findByLabelText('Reference'))
    fireEvent.click(await screen.findByLabelText('Cheque / transfer no.'))
    expect(screen.queryByLabelText('UTR')).toBeNull()
    expect(await within(table).findByText('SUP-INV-4471')).toBeInTheDocument()
    expect(within(table).getByText('000451')).toBeInTheDocument()
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
    fullAmounts()
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
    fullAmounts()
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
    fullAmounts()
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
    expect(screen.getByRole('region', { name: 'Overdue' })).toHaveTextContent('₹3.13 L')
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
    fullAmounts()
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
    fullAmounts()
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

const stockItem = (id: number, name: string, closing: string, value: string | null, rate: string | null) => ({
  item_id: id, name, group: 'Finished Goods', unit: 'Nos', companies: [3],
  opening: '20', inward: '30', outward: String(50 - Number(closing)), closing, value, rate,
})

const stockFound: StockOut = {
  companies: [3],
  combined: false,
  period: { start: '2026-04-01', end: '2026-09-30', months: [] },
  value_on: '2026-08-31',
  total_value: '1250000',
  items: [stockItem(41, 'Widget', '40', '1000000', '25000.00'), stockItem(42, 'Gadget', '-10', '250000', null)],
  by_group: [{ name: 'Finished Goods', value: '1250000' }],
  by_godown: [{ name: 'Main Location', value: '1250000' }],
  by_date: [{ date: '2026-05-31', value: '900000' }, { date: '2026-08-31', value: '1250000' }],
}

const stockPage: StockItemPageOut = {
  item: stockFound.items[0],
  period: stockFound.period,
  value_on: '2026-08-31',
  godown: null,
  movements: [
    { company: 3, date: '2026-05-02', voucher_id: 7, voucher_number: 'P-1', voucher_type: 'Purchase', godown: 'Main Location', other_godown: null, quantity: '30', balance: '50', amount: '600000' },
    { company: 3, date: '2026-08-02', voucher_id: 8, voucher_number: 'S-1', voucher_type: 'Sales', godown: 'Main Location', other_godown: null, quantity: '-10', balance: '40', amount: '-300000' },
  ],
  truncated: false,
  months: [
    { month: '2026-05-01', inward: '30', outward: '0', closing: '50', value: '900000' },
    { month: '2026-08-01', inward: '0', outward: '10', closing: '40', value: '1000000' },
  ],
  by_godown: [],
}

const godownRow = (item: string, godown: string | null, batch: string | null, quantity: string, value: string | null) =>
  ({ item_id: 41, item, unit: 'Nos', godown, batch, quantity, value })
const godownsFound: StockGodownsOut = {
  companies: [3],
  combined: false,
  period: stockFound.period,
  on: '2026-09-30',
  value_on: '2026-08-31',
  sections: [
    { key: 'ours', in_total: true, quantity: '157', value: '5460', rows: [godownRow('Widget', 'Main Location', 'B-1', '127', '5460'), godownRow('Widget', null, null, '0', null)] },
    { key: 'held_for_others', in_total: true, quantity: '30', value: '120', rows: [godownRow('Client Fabric', 'Principal Stock', null, '30', '120')] },
    { key: 'at_job_workers', in_total: false, quantity: '-60', value: null, rows: [godownRow('Steel Sheet', 'Job Worker Alpha', null, '-60', null)] },
  ],
  total_quantity: '187',
  total_value: '5580',
  godown_values: [{ name: 'Main Location', value: '5460' }, { name: 'Principal Stock', value: '120' }],
}

describe('the stock', () => {
  beforeEach(() => {
    window.localStorage.clear()
    stubApi({
      '/api/v1/companies': [companies[0]],
      '/api/v1/periods': periods,
      '/api/v1/stock': stockFound,
      '/api/v1/stock/41': stockPage,
    })
  })
  afterEach(() => vi.unstubAllGlobals())

  it('is a module of its own, with the stock summary', async () => {
    renderApp('#/overview/dashboard')
    expect((await screen.findByRole('link', { name: 'Stock' })).getAttribute('href')).toMatch(/^#\/stock\/summary/)
  })

  it('shows the value, the items with their quantities, value and rate, and negative stock', async () => {
    renderApp('#/stock/summary')
    const value = await screen.findByRole('region', { name: 'Stock value' })
    expect(value).toHaveTextContent('₹12.50 L')
    expect(value).toHaveTextContent('At 31-Aug-2026, the last stored date in the period')
    expect(screen.getByRole('region', { name: 'Items with negative stock' })).toHaveTextContent('1')
    const table = screen.getByRole('table', { name: 'Stock items' })
    const headers = within(table).getAllByRole('columnheader').map((h) => h.textContent)
    expect(headers).toEqual(['Item', 'Stock group', 'Unit', 'Opening qty', 'Inward qty', 'Outward qty', 'Closing qty', 'Rate', 'Value'])
    const widget = within(table).getByRole('link', { name: 'Widget' })
    expect(widget.getAttribute('href')).toMatch(/^#\/stock\/summary\/41/)
    expect(widget.closest('tr')).toHaveTextContent('₹10.00 L')
    expect(within(table).getByText('Gadget').closest('tr')).toHaveTextContent('-10')
    expect(screen.getByRole('list', { name: 'Stock value by godown' })).toHaveTextContent('Main Location')
    expect(document.querySelector('.header-crumbs')).toHaveTextContent('Stock/Stock summary')
  })

  it('opens an item with its movements, the quantity after each, and its months', async () => {
    renderApp('#/stock/summary/41')
    expect(await screen.findByRole('region', { name: 'Closing quantity' })).toHaveTextContent('40')
    expect(screen.getByRole('region', { name: 'Rate' })).toHaveTextContent('₹0.25 L')
    const movements = screen.getByRole('table', { name: 'Movements' })
    expect(within(movements).getByText('S-1').closest('tr')).toHaveTextContent('-10')
    expect(within(movements).getByText('S-1').closest('tr')).toHaveTextContent('40')
    fireEvent.click(screen.getByRole('tab', { name: 'Month by month' }))
    expect(await screen.findByRole('table', { name: 'Month by month' })).toHaveTextContent('Aug-2026')
    expect(document.querySelector('.header-crumbs')).toHaveTextContent('Stock/Stock summary/Widget')
  })

  it('says so for an item that is not there', async () => {
    renderApp('#/stock/summary/77')
    expect(await screen.findByText("The stock item couldn't be loaded.")).toBeInTheDocument()
  })
})

const line = (id: number, ledger: string, debit: string | null, credit: string | null, extra: object = {}) => ({
  line_id: id, company: 3, date: '2026-09-01', voucher_id: 31, voucher_type: 'Payment', voucher_number: 'CC-2', reference: null,
  party_id: null, party: null, gstin: null, ledger_id: 100 + id, ledger, particulars: null, debit, credit,
  narration: 'Electricity for September', bills: null, cost_centres: null, order_number: null, cheque: null,
  transaction_type: null, instrument_date: null, bank_cleared_date: null, tally_bank_entry_id: null,
  gst_registration: null, place_of_supply: null, party_gst_registration_type: null, gst_rates: null, irn: null, irn_date: null,
  eway_bill_number: null, eway_bill_date: null, ...extra,
})

const transactionsFound: TransactionsOut = {
  companies: [3],
  combined: false,
  period: { start: '2026-09-01', end: '2026-09-30', months: [] },
  rows: [
    line(1, 'Electricity', '4000', null, { particulars: 'HDFC Bank', cost_centres: 'Head Office, Project Alpha' }),
    line(2, 'HDFC Bank', null, '4000', {
      particulars: 'Electricity', cheque: '000451', transaction_type: 'Cheque',
      tally_bank_entry_id: '7GJ2K9QX4M1Z8P3T',
    }),
    line(3, 'Vendor Three', null, '600', {
      voucher_id: 32, voucher_type: 'Purchase', voucher_number: 'PI-9', reference: 'SUP-INV-4471', party_id: 7, party: 'Vendor Three',
      gstin: '29ABCDE1234F1Z5', particulars: 'Purchases', bills: 'PI-9', narration: null,
    }),
    line(4, 'Purchases', '600', null, {
      voucher_id: 32, voucher_type: 'Purchase', voucher_number: 'PI-9', reference: 'SUP-INV-4471', party_id: 7, party: 'Vendor Three',
      gstin: '29ABCDE1234F1Z5', particulars: 'Vendor Three', cost_centres: 'Branch', narration: null,
    }),
  ],
  truncated: false,
}

describe('the transactions', () => {
  beforeEach(() => {
    window.localStorage.clear()
    stubApi({ '/api/v1/companies': [companies[0]], '/api/v1/periods': periods, '/api/v1/transactions': transactionsFound })
  })
  afterEach(() => vi.unstubAllGlobals())

  it('is a page of the Books module', async () => {
    renderApp('#/overview/dashboard')
    expect((await screen.findByRole('link', { name: 'Books' })).getAttribute('href')).toMatch(/^#\/books\/transactions/)
  })

  it('lists every ledger line with its columns, in order, the cheque but never a UTR', async () => {
    fullAmounts()
    renderApp('#/books/transactions')
    const table = await screen.findByRole('table', { name: 'Transactions' })
    const headers = within(table).getAllByRole('columnheader').map((h) => h.textContent)
    expect(headers).toEqual([
      'Date', 'Voucher Type', 'Voucher Number', 'Reference Number', 'Party Name', 'Ledger Name', 'Particulars', 'Debit', 'Credit',
      'Narration', 'Bill Number', 'Cost Centre', 'Order Number', 'GSTIN', 'Cheque Number',
    ])
    const expense = within(table).getByText('Head Office, Project Alpha').closest('tr') as HTMLElement
    expect(expense).toHaveTextContent('Electricity')
    expect(expense).toHaveTextContent('HDFC Bank')
    expect(expense).toHaveTextContent('₹4,000.00')
    expect(within(table).getByText('000451')).toBeInTheDocument()
    expect(within(table).queryByText('7GJ2K9QX4M1Z8P3T')).toBeNull() // Tally's own id: a hidden column
    fireEvent.click(screen.getByRole('button', { name: 'Columns ▾' }))
    expect(await screen.findByLabelText('Cheque Number')).toBeInTheDocument()
    expect(screen.queryByLabelText('UTR')).toBeNull() // the UTR is stored, never shown
    const invoice = within(table).getAllByText('SUP-INV-4471')[0].closest('tr') as HTMLElement // the vendor's line
    expect(invoice).toHaveTextContent('Vendor Three')
    expect(invoice).toHaveTextContent('29ABCDE1234F1Z5')
    expect(invoice).toHaveTextContent('PI-9')
    const total = within(table).getByText('Total').closest('tr') as HTMLElement
    expect(total.textContent?.match(/₹4,600\.00/g)).toHaveLength(2) // debits equal credits
    expect(document.querySelector('.header-crumbs')).toHaveTextContent('Books/Transactions')
  })

  it('explains where the order number comes from', async () => {
    renderApp('#/books/transactions')
    const table = await screen.findByRole('table', { name: 'Transactions' })
    fireEvent.mouseEnter(within(table).getByText('Order Number'))
    expect(await screen.findByText(/orders the voucher is made against/)).toBeInTheDocument()
  })
})

describe('loading and errors (pulse loading, docs/design/dashboard.md Section 0.5)', () => {
  afterEach(() => vi.unstubAllGlobals())

  /** The API, where `held` paths wait until `release` is called, and `failing` paths fail as
   *  many times as given before they answer. */
  function stubHeldApi(answers: Record<string, unknown>, held: string[] = [], failing: Record<string, number> = {}) {
    requests = []
    const waiting: (() => void)[] = []
    const failures = { ...failing }
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        requests.push(url)
        const path = new URL(url).pathname
        if (held.includes(path)) await new Promise<void>((resolve) => waiting.push(resolve))
        if ((failures[path] ?? 0) > 0) {
          failures[path]--
          return new Response(JSON.stringify({ detail: 'Server error' }), { status: 500 })
        }
        return new Response(JSON.stringify(answers[path]))
      }),
    )
    return () => {
      held.length = 0
      waiting.splice(0).forEach((resolve) => resolve())
    }
  }

  const answers = { '/api/v1/companies': companies, '/api/v1/periods': periods, '/api/v1/reports/balance-sheet': sheetFound }

  it('shows a page in its own shape while it loads, busy and announced, then the figures', async () => {
    const release = stubHeldApi(answers, ['/api/v1/reports/balance-sheet'])
    renderApp('#/balance-sheet/statement')
    const area = await screen.findByTestId('loading')
    expect(area).toHaveAttribute('aria-busy', 'true')
    expect(within(area).getByText('Loading…')).toBeInTheDocument()
    expect(area.querySelector('.sheet-layout .ratio-tile')).not.toBeNull() // the statement's shape
    await waitFor(() => expect(area.querySelector('.loading-shapes')).toHaveClass('shown')) // after 150 ms
    release()
    expect(await screen.findByRole('table', { name: 'Balance Sheet' })).toBeInTheDocument()
    expect(screen.queryByTestId('loading')).toBeNull()
    expect(screen.queryByText('Loading…')).toBeNull()
  })

  it('shows a failed request plainly with Retry, which asks again and shows the figures', async () => {
    stubHeldApi(answers, [], { '/api/v1/reports/balance-sheet': 1 })
    renderApp('#/balance-sheet/statement')
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent("The Balance Sheet couldn't be loaded.")
    const asked = requests.filter((r) => r.includes('/reports/balance-sheet')).length
    fireEvent.click(within(alert).getByRole('button', { name: 'Retry' }))
    expect(await screen.findByRole('table', { name: 'Balance Sheet' })).toBeInTheDocument()
    expect(requests.filter((r) => r.includes('/reports/balance-sheet')).length).toBe(asked + 1)
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('retries the data plane itself when it could not be reached', async () => {
    stubHeldApi({ ...answers, '/api/v1/home': home }, [], { '/api/v1/companies': 1 })
    renderApp('#/overview/dashboard')
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent("The dashboard can't reach the data plane.")
    fireEvent.click(within(alert).getByRole('button', { name: 'Retry' }))
    expect(await screen.findByRole('region', { name: 'Net sales' })).toBeInTheDocument()
  })

  it('pulses the logo while the app\'s first data loads, then stops', async () => {
    const release = stubHeldApi({ ...answers, '/api/v1/home': home }, ['/api/v1/companies'])
    renderApp('#/overview/dashboard')
    const logo = screen.getByTestId('top-logo')
    expect(logo).toHaveAttribute('aria-busy', 'true')
    await waitFor(() => expect(screen.getByTestId('top-logo')).toHaveClass('logo-pulse')) // after 150 ms
    expect(screen.getByTestId('loading')).toHaveAttribute('aria-busy', 'true') // the page's shape meanwhile
    release()
    await screen.findByRole('region', { name: 'Net sales' })
    expect(screen.getByTestId('top-logo')).not.toHaveClass('logo-pulse')
    expect(screen.getByTestId('top-logo')).not.toHaveAttribute('aria-busy')
  })
})

// The formula sheet's text, given to the tests by vite.config.ts.
declare const __FORMULA_SHEET__: string
const formulaSheet = __FORMULA_SHEET__

describe('the stock by godown', () => {
  beforeEach(() => {
    window.localStorage.clear()
    stubApi({
      '/api/v1/companies': [companies[0]],
      '/api/v1/periods': periods,
      '/api/v1/stock/godowns': godownsFound,
      '/api/v1/stock/41': { ...stockPage, godown: 'Branch Store', by_godown: godownsFound.sections,
        movements: [{ ...stockPage.movements[0], godown: 'Branch Store', other_godown: 'Main Location' }] },
    })
  })
  afterEach(() => vi.unstubAllGlobals())

  it('is a page of the Stock module, with the three sections in plain words and what is in the total', async () => {
    renderApp('#/stock/godowns')
    const total = await screen.findByRole('region', { name: 'Stock in the total' })
    expect(total).toHaveTextContent('187')
    expect(total).toHaveTextContent("as Tally's Stock Summary")
    expect(within(screen.getByRole('navigation', { name: 'Stock pages' })).getByRole('link', { name: 'By godown' })).toHaveAttribute('aria-current', 'page')
    const ours = screen.getByRole('region', { name: 'Our stock' })
    expect(ours).toHaveTextContent('In the total')
    const others = screen.getByRole('region', { name: "Others' stock held with us (not ours)" })
    expect(others).toHaveTextContent('In the total')
    expect(others).toHaveTextContent("It isn't ours, but Tally's Stock Summary and closing stock include it")
    const workers = screen.getByRole('region', { name: 'Our stock at job workers (still ours)' })
    expect(workers).toHaveTextContent('Not in the total')
    expect(workers).toHaveTextContent('Tally leaves it out of its Stock Summary and closing stock')
    expect(within(workers).getAllByText('-60').length).toBeGreaterThan(0) // the row and its total
    // Every row opens the item's page at that godown; an opening not split by godown opens the whole item.
    const table = within(ours).getByRole('table', { name: 'Our stock' })
    const main = within(table).getAllByRole('link', { name: 'Main Location' })[0]
    expect(main.getAttribute('href')).toMatch(/^#\/stock\/summary\/41\?.*godown=Main\+Location/)
    const notSplit = within(table).getByRole('link', { name: '(opening, not split by godown)' })
    expect(notSplit.getAttribute('href')).not.toContain('godown=')
  })

  it('opens an item at one godown: its movements there, the other godown of a move, and its breakdown', async () => {
    renderApp('#/stock/summary/41?godown=Branch+Store')
    expect(await screen.findByText('At Branch Store')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Show every godown' }).getAttribute('href')).not.toContain('godown=')
    expect(requests.some((r) => r.includes('/api/v1/stock/41?') && r.includes('godown=Branch+Store'))).toBe(true)
    const movements = screen.getByRole('table', { name: 'Movements' })
    expect(within(movements).getByText('Other godown')).toBeInTheDocument()
    expect(within(movements).getByText('Main Location')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('tab', { name: 'By godown and batch' }))
    expect(await screen.findByRole('region', { name: 'Our stock at job workers (still ours)' })).toBeInTheDocument()
  })

  it('explains how the page divides stock in a note, open the first time, which can be closed and stays closed', async () => {
    renderApp('#/stock/godowns')
    const title = await screen.findByText('How this page divides stock')
    const note = title.closest('details') as HTMLDetailsElement
    expect(note.open).toBe(true)
    // One point per section, under the section's own title, as in the sections below.
    expect(within(note).getByText('Our stock:')).toBeInTheDocument()
    expect(within(note).getByText("Others' stock held with us (not ours):")).toBeInTheDocument()
    expect(within(note).getByText('Our stock at job workers (still ours):')).toBeInTheDocument()
    expect(note).toHaveTextContent("Tally counts them in its Stock Summary, so we count them in the total too.")
    expect(note).toHaveTextContent('That is why it can show a negative quantity, and why it is not added to the total.')
    expect(note).toHaveTextContent("The total on this page equals Tally's Stock Summary for the same date.")
    // Closed by the reader: remembered in this browser, so it starts closed next time.
    fireEvent.click(title)
    await waitFor(() => expect(note.open).toBe(false))
    await waitFor(() => expect(window.localStorage.getItem('ledgerbridge.godownNote')).toBe('closed'))
    cleanup()
    renderApp('#/stock/godowns')
    const again = (await screen.findByText('How this page divides stock')).closest('details') as HTMLDetailsElement
    expect(again.open).toBe(false)
  })

  it('says plainly when the stock by godown fails, with Retry', async () => {
    stubApi({ '/api/v1/companies': [companies[0]], '/api/v1/periods': periods })
    renderApp('#/stock/godowns')
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent("The stock by godown couldn't be loaded.")
    expect(within(alert).getByRole('button', { name: /Retry/ })).toBeInTheDocument()
  })
})

describe('the voucher page and Explore', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('shows a voucher: its header, lines with equal totals, bills and stock', async () => {
    fullAmounts()
    stubApi({ '/api/v1/companies': companies, '/api/v1/periods': periods, '/api/v1/vouchers/7': voucherFound })
    renderApp('#/books/vouchers/7')
    const lines = await screen.findByRole('table', { name: 'Ledger lines' })
    expect(screen.getAllByRole('heading', { name: /Sales S-1/ }).length).toBeGreaterThan(0) // header and report title
    expect(within(lines).getByText('Sales - Goods').closest('tr')).toHaveTextContent('₹1,00,000.00')
    expect(screen.getByText(/Total debit/)).toHaveTextContent('Total debit ₹1,18,000.00 · total credit ₹1,18,000.00')
    expect(within(screen.getByRole('table', { name: 'Bills' })).getByText('New Ref')).toBeInTheDocument()
    expect(within(screen.getByRole('table', { name: 'Stock' })).getByRole('link', { name: 'Widget' }).getAttribute('href')).toMatch(/^#\/stock\/summary\/41/)
    // A detail page: no tab of its own in Books.
    expect(screen.queryByRole('link', { name: 'Voucher' })).toBeNull()
  })

  it('says plainly when a voucher is not there', async () => {
    stubApi({ '/api/v1/companies': companies, '/api/v1/periods': periods })
    renderApp('#/books/vouchers/99')
    expect(await screen.findByText("The voucher couldn't be loaded.")).toBeInTheDocument()
  })

  it('explores a dataset: columns, the period as the dates, CSV and saved views', async () => {
    window.localStorage.clear()
    stubApi({
      '/api/v1/companies': companies, '/api/v1/periods': periods,
      '/api/v1/datasets': datasetsFound, '/api/v1/datasets/voucher_lines': datasetResult,
      '/api/v1/datasets/voucher_lines/values/ledger': [{ id: 5, label: 'Customer One' }],
    })
    renderApp('#/data/explore?from=2026-04-01&to=2026-04-30')
    const note = (await screen.findByText('How this page works')).closest('details') as HTMLDetailsElement
    expect(note.open).toBe(true)
    const table = await screen.findByRole('table', { name: 'Voucher lines result' })
    expect(within(screen.getByRole('navigation', { name: 'Data pages' })).getByRole('link', { name: 'Explore' })).toHaveAttribute('aria-current', 'page')
    expect(within(table).getAllByRole('columnheader').map((h) => h.textContent)).toEqual(['Date', 'Ledger', 'Debit', 'Credit'])
    expect(within(table).getByText('Debit')).toHaveAttribute('data-formula', 'F-TRN-001')
    expect(within(table).getByText('Total').closest('tr')).toHaveTextContent('₹1.18 L')
    const asked = requests.filter((r) => r.includes('/api/v1/datasets/voucher_lines?')).pop() ?? ''
    expect(asked).toContain('date_from=2026-04-01') // the dates follow the top bar's period
    expect(asked).toContain('column=date&column=ledger')
    expect(screen.getByRole('link', { name: 'Export CSV' }).getAttribute('href')).toMatch(/\/api\/v1\/datasets\/voucher_lines\/csv\?.*column=ledger/)
    // A saved view keeps the choices in this browser.
    fireEvent.change(screen.getByRole('textbox', { name: 'View name' }), { target: { value: 'April lines' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save view' }))
    expect(window.localStorage.getItem('ledgerbridge.views.explore')).toContain('April lines')
  })

  it('shows a plain error with Retry when a dataset fails', async () => {
    stubApi({ '/api/v1/companies': companies, '/api/v1/periods': periods, '/api/v1/datasets': datasetsFound })
    renderApp('#/data/explore')
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent("The result couldn't be loaded.")
    expect(within(alert).getByRole('button', { name: /Retry/ })).toBeInTheDocument()
  })
})

describe('every figure on every page names its formula (docs/formula-sheet.md)', () => {
  afterEach(() => vi.unstubAllGlobals())

  // The sheet's IDs: "#### F-SAL-004 Net sales"; a retired entry says "(retired)" in its heading.
  const headings = [...formulaSheet.matchAll(/^#### (F-[A-Z]{2,3}-\d{3}) (.*)$/gm)]
  const known = new Set(headings.filter(([, , name]) => !/\(retired\)/i.test(name)).map(([, id]) => id))
  const answers = {
    '/api/v1/companies': companies,
    '/api/v1/periods': periods,
    '/api/v1/home': home,
    '/api/v1/reports/profit-loss': statement,
    '/api/v1/reports/balance-sheet': sheetFound,
    '/api/v1/sales/dashboard': sales,
    '/api/v1/purchases/dashboard': sales,
    '/api/v1/registers/sales': salesRegister,
    '/api/v1/registers/purchases': { ...salesRegister, side: 'purchases' },
    '/api/v1/monthly/sales': monthlySales,
    '/api/v1/monthly/purchases': { ...monthlySales, side: 'purchases' },
    '/api/v1/sales/channels': channelsFound,
    '/api/v1/parties/customers': partiesFound,
    '/api/v1/parties/customers/11': partyFound,
    '/api/v1/parties/vendors': { ...partiesFound, kind: 'vendors' },
    '/api/v1/ageing/customers': ageingFound,
    '/api/v1/ageing/vendors': { ...ageingFound, kind: 'vendors' },
    '/api/v1/cost-centres': centresFound,
    '/api/v1/cost-centres/21': centreFound,
    '/api/v1/stock': stockFound,
    '/api/v1/stock/41': stockPage,
    '/api/v1/stock/godowns': godownsFound,
    '/api/v1/transactions': transactionsFound,
    '/api/v1/vouchers/7': voucherFound,
    '/api/v1/datasets': datasetsFound,
    '/api/v1/datasets/voucher_lines': datasetResult,
    '/api/v1/cash-flow': {
      companies: [3, 4], combined: true, start: '2026-04-01', end: '2026-10-30', opening: '1000000', closing: '1200000',
      movements: [{ key: 'customers', label: 'Customers', inflow: '900000', outflow: '0', net: '900000' }],
      monthly: [{ month: '2026-04-01', inflow: '900000', outflow: '700000' }],
    },
  }
  const pages = [
    'overview/dashboard', 'sales/dashboard', 'sales/register', 'sales/monthly', 'sales/channels', 'sales/customers',
    'sales/customers/11', 'purchases/dashboard', 'purchases/register', 'purchases/monthly', 'purchases/vendors',
    'pnl/profit-loss', 'pnl/cost-centres', 'pnl/cost-centres/21', 'balance-sheet/statement', 'stock/summary',
    'stock/summary/41', 'stock/godowns', 'books/vouchers/7', 'data/explore', 'cash-flow/movement', 'parties/receivables', 'parties/payables', 'books/transactions',
    'data/health',
  ]

  it('reads the sheet', () => {
    expect(known.size).toBeGreaterThan(80)
  })

  it.each(pages)('#/%s', async (page) => {
    stubApi(answers)
    renderApp(`#/${page}`)
    await waitFor(() => expect(document.querySelectorAll('[data-figure]').length).toBeGreaterThan(0))
    await waitFor(() => expect(screen.queryByTestId('loading')).toBeNull())
    const figures = [...document.querySelectorAll<HTMLElement>('[data-figure]')]
    const named = (f: HTMLElement) => `${f.dataset.figure} "${f.getAttribute('aria-label') ?? f.textContent?.trim().slice(0, 40)}"`
    const without = figures.filter((f) => !f.dataset.formula).map(named)
    expect(without, 'figures with no formula ID').toEqual([])
    const unknown = figures.filter((f) => !known.has(f.dataset.formula ?? '')).map((f) => `${named(f)}: ${f.dataset.formula}`)
    expect(unknown, 'formula IDs not in the sheet, or retired').toEqual([])
  })
})
