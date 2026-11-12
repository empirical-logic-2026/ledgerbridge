// The modules and their pages (docs/design/dashboard.md Section 0.4, ADR-050): the module tabs
// of the top bar, in their order, and each module's pages as the tabs under the page header. A
// page is offered once it is built (`built`); a module once it has a built page. Each page says
// which facets its figures can be filtered by. Links made before the modules (e.g.
// "#/statements/profit-loss") still open their page (`MOVED`).

import { href, type Query } from '../router.ts'

export type Facet = 'customer' | 'channel' | 'ledger_group' | 'voucher_type'

export interface NavPage {
  key: string // the second part of the path: "#/<module>/<page>"
  label: string
  built: boolean
  facets: Facet[] // the facets this page applies; the others aren't offered
  whyNoFacets?: string // why a page takes no facets
  detail?: boolean // opened from a link with an id (a voucher), not listed as a tab
}

export interface NavGroup {
  key: string // the module
  label: string
  pages: NavPage[]
}

const STATEMENT = 'A whole statement covers every customer, channel and voucher type: filter on the Sales pages.'

const DATA = 'Data health covers each company whole.'

const COST_CENTRES = 'Each cost centre is shown whole: filter the list with its own filter, or open the cost centre.'

const STOCK = 'Each item is shown whole: filter the list with its own filter, or open the item.'

const BOOKS = 'Every line is listed: filter the table with its own filter, or group it.'

const PARTIES = 'Each party is shown whole: filter the list with its own filter, or open the party.'

const page = (key: string, label: string, built = false, facets: Facet[] = [], whyNoFacets?: string): NavPage => ({
  key,
  label,
  built,
  facets,
  whyNoFacets,
})

/** A page opened from a link with an id ("#/books/vouchers/12"), not listed as a tab. */
const detailPage = (key: string, label: string, whyNoFacets: string): NavPage => ({ ...page(key, label, true, [], whyNoFacets), detail: true })

const VOUCHER = 'One voucher is shown whole.'

const LEDGER = "One ledger is shown whole: filter its entries with the table's own filter."

const EXPLORE = 'Each dataset has its own filters: choose them on the page.'

export const NAV: NavGroup[] = [
  { key: 'overview', label: 'Overview', pages: [page('dashboard', 'Overview', true, [], 'The Overview shows the whole business; the Sales pages take filters.')] },
  {
    key: 'sales',
    label: 'Sales',
    pages: [
      page('dashboard', 'Sales dashboard', true, ['customer', 'channel']),
      page('register', 'Sales register', true, ['customer', 'channel']),
      page('monthly', 'Monthly sales', true, ['customer', 'channel']),
      page('channels', 'Channels', true, ['customer', 'channel']),
      page('customers', 'Customers', true, [], PARTIES),
    ],
  },
  {
    key: 'purchases',
    label: 'Purchases',
    pages: [
      page('dashboard', 'Purchases dashboard', true, ['voucher_type']),
      page('register', 'Purchase register', true, ['voucher_type']),
      page('monthly', 'Monthly purchases', true, ['voucher_type']),
      page('vendors', 'Vendors', true, [], PARTIES),
    ],
  },
  {
    key: 'pnl',
    label: 'P&L & KPIs',
    pages: [
      page('profit-loss', 'Profit & Loss', true, [], STATEMENT),
      page('trial-balance', 'Trial Balance', true, [], STATEMENT),
      page('cost-centres', 'Cost centres', true, [], COST_CENTRES),
    ],
  },
  { key: 'balance-sheet', label: 'Balance Sheet', pages: [page('statement', 'Balance Sheet', true, [], STATEMENT)] },
  { key: 'stock', label: 'Stock', pages: [page('summary', 'Stock summary', true, [], STOCK), page('godowns', 'By godown', true, [], STOCK)] },
  { key: 'cash-flow', label: 'Cash Flow', pages: [page('movement', 'Cash movement', true, [], STATEMENT)] },
  { key: 'parties', label: 'Parties', pages: [page('receivables', 'Receivables', true, [], PARTIES), page('payables', 'Payables', true, [], PARTIES)] },
  {
    key: 'books',
    label: 'Books',
    pages: [page('transactions', 'Transactions', true, [], BOOKS), page('ledger', 'Ledger statement', true, [], LEDGER), detailPage('vouchers', 'Voucher', VOUCHER)],
  },
  {
    key: 'data',
    label: 'Data',
    pages: [page('health', 'Data health', true, [], DATA), page('explore', 'Explore', true, [], EXPLORE), page('companies', 'Companies', true, [], DATA)],
  },
]

export const HOME: [string, string] = ['overview', 'dashboard']

/** Pages that moved, from their old path to their module's ("statements/profit-loss"). */
export const MOVED: Record<string, [string, string]> = {
  'statements/profit-loss': ['pnl', 'profit-loss'],
}

/** The modules with at least one built page, and only their built pages. */
export function builtNav(): NavGroup[] {
  return NAV.map((g) => ({ ...g, pages: g.pages.filter((p) => p.built) })).filter((g) => g.pages.length > 0)
}

/** The path a page lives at now: a moved page's new path, the rest (e.g. a detail page's id)
 *  kept. */
export function currentPath(path: string[]): string[] {
  const moved = MOVED[path.slice(0, 2).join('/')]
  return moved ? [...moved, ...path.slice(2)] : path
}

/** The module and page a path names ("#/" is the Overview); undefined for an unknown one. */
export function findPage(path: string[]): { group: NavGroup; page: NavPage } | undefined {
  const [groupKey, pageKey] = path.length ? currentPath(path) : HOME
  const group = NAV.find((g) => g.key === groupKey)
  const found = group?.pages.find((p) => p.key === (pageKey ?? group.pages[0]?.key))
  return group && found?.built ? { group, page: found } : undefined
}

/** A link to a page (and, for a detail page, its id: ["sales", "customers", "12"]), or
 *  undefined while that page isn't built: nothing links to a page that isn't there. */
export function builtHref(path: string[], query: Query): string | undefined {
  return findPage(path) ? href(currentPath(path), query) : undefined
}

/** A ledger's Ledger statement for the same selection (ADR-055); undefined without a ledger. */
export function ledgerHref(ledgerId: number | null | undefined, query: Query): string | undefined {
  return ledgerId ? builtHref(['books', 'ledger', String(ledgerId)], query) : undefined
}
