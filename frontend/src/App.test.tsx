import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { App as AntApp } from 'antd'
import App from './App.tsx'
import type { ChannelsOut, Company, Home, MonthlyOut, Periods, RegisterOut, SalesDashboard } from './api/types.ts'

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
    expect(within(side).queryByText('Parties')).toBeNull() // a group shows once it has a page
    expect(within(side).getByRole('link', { name: 'Sales dashboard' })).toHaveAttribute('href', '#/sales/dashboard')
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

const sales: SalesDashboard = {
  companies: [3, 4],
  combined: true,
  period: { start: '2026-04-01', end: '2026-09-30', months: [] },
  compared: true,
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
  top_customers: [
    { company: 3, party_id: 11, name: 'Customer One', net_sales: '300000000', invoices: 70 },
    { company: 4, party_id: 12, name: 'Customer Two', net_sales: '100000000', invoices: 40 },
  ],
  other_customers: '82000000',
  customers: 9,
  largest_invoices: [
    { voucher_id: 501, company: 3, date: '2026-05-04', number: 'S-17', voucher_type: 'Sales', party_id: 11, party: 'Customer One', amount: '50000000' },
    { voucher_id: 502, company: 4, date: '2026-04-09', number: 'S-3', voucher_type: 'Online Sales', party_id: 12, party: 'Customer Two', amount: '20000000' },
  ],
}

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
    expect(document.querySelector('.top-crumbs')).toHaveTextContent('Sales/Sales dashboard')
  })

  it('applies the customer and channel facets, and no others', async () => {
    renderApp('#/sales/dashboard?customer=Customer%20One&channel=Sales')
    await screen.findByRole('region', { name: 'Net sales' })
    expect(lastRequest()).toContain('customer=Customer+One')
    expect(lastRequest()).toContain('channel=Sales')
    expect(screen.getByRole('button', { name: 'Voucher type (not used on this page)' })).toBeDisabled()
  })

  it('lists the months, customers and invoices, each linking deeper where a page exists', async () => {
    renderApp('#/sales/dashboard?company=3&company=4')
    const months = await screen.findByRole('table', { name: 'Sales by month' })
    // A month opens its register.
    expect(within(months).getByRole('link', { name: 'Apr-2026' }).getAttribute('href')).toMatch(/^#\/sales\/register\?.*month=2026-04/)
    expect(within(months).getByText('Total')).toBeInTheDocument()
    const customers = screen.getByRole('table', { name: 'Top customers' })
    // The customer page isn't built yet: a customer filters this page.
    expect(within(customers).getByRole('link', { name: 'Customer One' }).getAttribute('href')).toContain('customer=Customer+One')
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

  it('explains itself in the options panel', async () => {
    renderApp('#/sales/dashboard')
    const panel = await screen.findByRole('complementary', { name: 'Sales options' })
    expect(within(panel).getByText(/Sales Accounts group/)).toBeInTheDocument()
    expect(within(panel).getByRole('link', { name: 'Profit & Loss →' })).toBeInTheDocument()
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
    expect(document.querySelector('.top-crumbs')).toHaveTextContent('Sales/Sales register')
  })

  it('asks for the customer and channel facets by name', async () => {
    renderApp('#/sales/register?customer=Customer%20One&channel=Sales')
    await screen.findByRole('table', { name: 'Sales register' })
    const asked = requests.filter((r) => r.includes('/registers/sales')).pop() ?? ''
    expect(asked).toContain('party=Customer+One')
    expect(asked).toContain('voucher_type=Sales')
  })

  it('links a customer to the register filtered to them while their page is not built', async () => {
    renderApp('#/sales/register')
    const table = await screen.findByRole('table', { name: 'Sales register' })
    const link = within(table).getAllByRole('link', { name: 'Customer One' })[0]
    expect(link.getAttribute('href')).toMatch(/^#\/sales\/register\?.*customer=Customer\+One/)
    expect(within(table).queryByRole('link', { name: 'V-1' })).toBeNull() // no voucher page yet
  })

  it('says when a register was cut short, and explains itself', async () => {
    renderApp('#/purchases/register')
    expect(await screen.findByText(/Only the first 0 vouchers are shown/)).toBeInTheDocument()
    const panel = screen.getByRole('complementary', { name: 'Purchase register options' })
    expect(within(panel).getByText(/Debit Note Register/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Customer (not used on this page)' })).toBeDisabled()
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
    expect(screen.getByRole('complementary', { name: 'Monthly sales options' })).toHaveTextContent(/financial year/)
  })

  it('has monthly purchases opening the purchase register', async () => {
    renderApp('#/purchases/monthly')
    const table = await screen.findByRole('table', { name: 'Monthly purchases' })
    expect(within(table).getByRole('link', { name: 'May-2026' }).getAttribute('href')).toMatch(/^#\/purchases\/register\?.*month=2026-05/)
    expect(document.querySelector('.top-crumbs')).toHaveTextContent('Purchases/Monthly purchases')
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
