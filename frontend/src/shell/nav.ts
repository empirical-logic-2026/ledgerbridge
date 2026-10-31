// The side bar's groups and pages (docs/design/dashboard.md Section 0.2), in their order. A
// page is listed once it is built (`built`); a group once it has a built page. Each page says
// which of the top filter bar's facets its figures can be filtered by.

export type Facet = 'customer' | 'channel' | 'ledger_group' | 'voucher_type'

export interface NavPage {
  key: string // the second part of the path: "#/<group>/<page>"
  label: string
  built: boolean
  facets: Facet[] // the facets this page applies; the others are shown disabled
  whyNoFacets?: string // shown on the disabled facets
}

export interface NavGroup {
  key: string
  label: string
  pages: NavPage[]
}

const STATEMENT = 'A whole statement covers every customer, channel and voucher type: filter on the Sales and Books pages.'

const page = (key: string, label: string, built = false, facets: Facet[] = [], whyNoFacets?: string): NavPage => ({
  key,
  label,
  built,
  facets,
  whyNoFacets,
})

export const NAV: NavGroup[] = [
  { key: 'overview', label: 'Overview', pages: [page('dashboard', 'Dashboard', true, [], 'The Dashboard shows the whole business; the Sales pages take these filters.')] },
  {
    key: 'sales',
    label: 'Sales',
    pages: [page('dashboard', 'Sales dashboard'), page('register', 'Sales register'), page('customers', 'Customers'), page('channels', 'Channels')],
  },
  { key: 'purchases', label: 'Purchases', pages: [page('register', 'Purchase register'), page('vendors', 'Vendors')] },
  {
    key: 'statements',
    label: 'Statements',
    pages: [page('profit-loss', 'Profit & Loss', true, [], STATEMENT), page('balance-sheet', 'Balance Sheet'), page('trial-balance', 'Trial Balance')],
  },
  {
    key: 'books',
    label: 'Books',
    pages: [page('day-book', 'Day Book'), page('vouchers', 'Vouchers'), page('ledgers', 'Ledgers'), page('cash-bank', 'Cash & Bank')],
  },
  { key: 'parties', label: 'Parties', pages: [page('receivables', 'Receivables'), page('payables', 'Payables')] },
  { key: 'data', label: 'Data', pages: [page('health', 'Data health'), page('companies', 'Companies')] },
]

export const HOME: [string, string] = ['overview', 'dashboard']

/** The groups with at least one built page, and only their built pages. */
export function builtNav(): NavGroup[] {
  return NAV.map((g) => ({ ...g, pages: g.pages.filter((p) => p.built) })).filter((g) => g.pages.length > 0)
}

/** The group and page a path names ("#/" is the Dashboard); undefined for an unknown one. */
export function findPage(path: string[]): { group: NavGroup; page: NavPage } | undefined {
  const [groupKey, pageKey] = path.length ? path : HOME
  const group = NAV.find((g) => g.key === groupKey)
  const found = group?.pages.find((p) => p.key === (pageKey ?? group.pages[0]?.key))
  return group && found?.built ? { group, page: found } : undefined
}
