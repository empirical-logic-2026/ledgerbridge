import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
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
      <App mode="light" onMode={onMode} today="2026-10-30" now={new Date('2026-10-30T09:00:00')} />
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

  it('opens on the apps home: greeting, sync status and a tile per app', async () => {
    renderApp('#/')
    expect(await screen.findByRole('heading', { name: 'Good morning' })).toBeInTheDocument()
    expect(await screen.findByText('Choose an app. Everything updates automatically from Tally.')).toBeInTheDocument()
    expect(screen.getByText(/Tally: 1 loaded · synced .* · all checks passed/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Reports/ })).toHaveAttribute('href', '#/reports')
    expect(screen.getByText('This computer only')).toBeInTheDocument()
  })

  it('shows the Profit & Loss and Balance Sheet cards, combined, in lakhs and crores', async () => {
    renderApp('#/reports')
    const pl = await screen.findByRole('region', { name: 'Profit & Loss' })
    expect(within(pl).getByText('₹48.20 Cr')).toBeInTheDocument()
    expect(within(pl).getByText('▲ 12%')).toHaveClass('good')
    expect(within(pl).getByText('▲ 9%')).toHaveClass('watch') // costs up: watch
    expect(within(pl).getByText(/Runs to 02-Oct-2026/)).toBeInTheDocument()
    const bs = screen.getByRole('region', { name: 'Balance Sheet' })
    expect(within(bs).getByText('₹62.80 Cr')).toBeInTheDocument()
    expect(within(screen.getByRole('region', { name: 'Stock value' })).getByText('—')).toBeInTheDocument()
    expect(screen.getByText(/without inter-company eliminations/)).toBeInTheDocument()
    expect(screen.getByText('71%')).toBeInTheDocument()
    expect(screen.getByTestId('chart')).toBeInTheDocument()
  })

  it('marks each company loaded or not loaded, as the last check found it', async () => {
    renderApp('#/reports')
    const alpha = await screen.findByRole('button', { name: /Alpha/ })
    expect(within(alpha).getByText('loaded')).toBeInTheDocument()
    expect(within(screen.getByRole('button', { name: /Beta/ })).getByText('not loaded')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'All combined' })).toHaveAttribute('aria-pressed', 'true')
  })

  it('asks for the months up to now by default, and any company combination chosen', async () => {
    renderApp('#/reports')
    await screen.findByRole('region', { name: 'Profit & Loss' })
    const asked = lastHomeRequest()
    expect(asked).toContain('company=3&company=4')
    expect(asked).toContain('month=2026-04')
    expect(asked).toContain('month=2026-10')
    expect(asked).not.toContain('month=2026-11')
    fireEvent.click(screen.getByRole('button', { name: /Beta/ }))
    expect(window.location.hash).toContain('company=4')
  })

  it('takes chosen months, or a date range typed as DD-MMM-YYYY', async () => {
    renderApp('#/reports?month=2026-04&month=2026-06')
    await screen.findByRole('region', { name: 'Profit & Loss' })
    expect(lastHomeRequest()).toMatch(/month=2026-04&month=2026-06.*compare=true/)
    const from = screen.getByLabelText('From')
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
    renderApp('#/reports?from=2026-04-01&to=2026-09-15')
    expect(
      await screen.findByText(/Profit isn't available: no statement is stored for 15-Sep-2026/),
    ).toBeInTheDocument()
    expect(lastHomeRequest()).toContain('date_from=2026-04-01&date_to=2026-09-15')
  })

  it('switches between light and dark', async () => {
    const onMode = renderApp('#/reports')
    fireEvent.click(await screen.findByRole('button', { name: 'Switch to dark mode' }))
    expect(onMode).toHaveBeenCalledWith('dark')
  })

  it('says so when no company is visible', async () => {
    stubApi({ '/api/v1/companies': [] })
    renderApp('#/reports')
    expect(await screen.findByText('No companies to show yet.')).toBeInTheDocument()
  })

  it('shows the API being unreachable plainly', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    renderApp('#/reports')
    expect(await screen.findByText("The dashboard can't reach the data plane.")).toBeInTheDocument()
  })

  it('has a page for unknown addresses', async () => {
    renderApp('#/nowhere')
    expect(await screen.findByText('There is no such page')).toBeInTheDocument()
  })
})
