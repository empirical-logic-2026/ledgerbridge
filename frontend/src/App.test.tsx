import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App.tsx'
import type { Company, Overview, Periods } from './api/types.ts'

// ECharts needs a real canvas; the wrapper is exercised in the browser, not jsdom.
vi.mock('./components/EChart.tsx', () => ({ EChart: () => <div data-testid="chart" /> }))

const health = {
  last_sync_at: '2026-10-30T10:00:00',
  validation_status: 'passed',
  validated_as_of: '2026-10-02',
  validated_at: '2026-10-30T10:00:00',
}
const companies: Company[] = [
  { id: 3, code: 'ALPHA', name: 'Alpha Traders', books_from: '2025-04-01', fy_start_month: 4, health },
  {
    id: 4,
    code: 'BETA',
    name: 'Beta Exports',
    books_from: '2025-04-01',
    fy_start_month: 4,
    health: { ...health, validation_status: 'failed' },
  },
]
const periods: Periods = {
  financial_years: [{ start_year: 2026, label: 'FY 2026-27', start: '2026-04-01', end: '2027-03-31' }],
  as_at_dates: ['2026-09-30'],
}
const overview: Overview = {
  companies: [3, 4],
  combined: true,
  period_start: '2026-04-01',
  as_of: '2026-09-30',
  sales: '48200000.0000',
  purchases: '30150000.0000',
  gross_profit: '6240000.0000',
  net_profit: null,
  cash_and_bank: '11500000.0000',
  receivables: '3860000.0000',
  payables: '1250000.0000',
  monthly_sales: [{ month: '2026-04-01', net_sales: '8000000.0000' }],
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
      <App mode="light" onMode={onMode} today="2026-10-30" />
    </QueryClientProvider>,
  )
  return onMode
}

describe('the dashboard', () => {
  beforeEach(() =>
    stubApi({ '/api/v1/companies': companies, '/api/v1/periods': periods, '/api/v1/overview': overview }),
  )
  afterEach(() => vi.unstubAllGlobals())

  it('opens on the apps home with a tile per app', async () => {
    renderApp('#/')
    expect(await screen.findByRole('heading', { name: 'Apps' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Sales, profit, cash/ })).toHaveAttribute('href', '#/overview')
    expect(screen.getByText('This computer only')).toBeInTheDocument()
  })

  it('shows the Overview in lakhs and crores, combined across companies', async () => {
    renderApp('#/overview')
    expect(await screen.findByText('₹4.82 Cr')).toBeInTheDocument() // sales
    expect(screen.getByText('₹62.4 L')).toBeInTheDocument() // gross profit
    expect(screen.getByText('—')).toBeInTheDocument() // net profit: no statement stored
    expect(screen.getAllByText(/without inter-company eliminations/).length).toBeGreaterThan(0)
    expect(screen.getByTestId('chart')).toBeInTheDocument()
    const healthCard = screen.getByText('Data health').closest('.ant-card') as HTMLElement
    expect(within(healthCard).getByText('Checks passed')).toBeInTheDocument()
    expect(within(healthCard).getByText('Checks failed')).toBeInTheDocument()
    const asked = requests.find((r) => r.includes('/api/v1/overview')) ?? ''
    expect(asked).toContain('company=3&company=4')
    expect(asked).toContain('financial_year=2026')
    expect(asked).toContain('as_of=2026-09-30')
  })

  it('asks for one company when one is chosen in the URL', async () => {
    renderApp('#/overview?company=4')
    await screen.findByText('₹4.82 Cr')
    const asked = requests.filter((r) => r.includes('/api/v1/overview')).pop() ?? ''
    expect(asked).toContain('company=4')
    expect(asked).not.toContain('company=3')
  })

  it('switches between light and dark', async () => {
    const onMode = renderApp('#/overview')
    fireEvent.click(await screen.findByRole('button', { name: 'Switch to dark mode' }))
    expect(onMode).toHaveBeenCalledWith('dark')
  })

  it('says so when no company is visible', async () => {
    stubApi({ '/api/v1/companies': [] })
    renderApp('#/overview')
    expect(await screen.findByText('No companies to show yet.')).toBeInTheDocument()
  })

  it('shows the API being unreachable plainly', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    renderApp('#/overview')
    expect(await screen.findByText("The dashboard can't reach the data plane.")).toBeInTheDocument()
  })

  it('has a page for unknown addresses', async () => {
    renderApp('#/nowhere')
    expect(await screen.findByText('There is no such page')).toBeInTheDocument()
  })
})
