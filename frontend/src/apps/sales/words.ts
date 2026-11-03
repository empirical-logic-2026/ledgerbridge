// The words and links of each side of the trade dashboard (SalesDashboard.tsx): sales with the
// customers and channels, purchases with the vendors and voucher types.

import type { Facet } from '../../shell/nav.ts'

export type Side = 'sales' | 'purchases'

export interface SideWords {
  module: Side // the module and the API's path
  net: string
  returns: string
  party: string // one of them
  parties: string // the list's page under the module, and the word in a sentence
  top: string
  facet: Facet // the facet a mix part (and a party, for sales) filters by
  loadError: string
  byMonth: string
  byMonthTable: string
  mix: string
  mixLabel: string
  ledgers: string
  options: string
  page: string // saved views' key
  register: string // the register in the source
  notes: string // the returns' register in the source
  group: string // the source's group
}

export const SIDE_WORDS: Record<Side, SideWords> = {
  sales: {
    module: 'sales',
    net: 'Net sales',
    returns: 'Sales returns',
    party: 'Customer',
    parties: 'customers',
    top: 'Top customers',
    facet: 'channel',
    loadError: "The sales couldn't be loaded.",
    byMonth: 'Net sales by month',
    byMonthTable: 'Sales by month',
    mix: 'Sales by channel',
    mixLabel: 'Net sales by channel',
    ledgers: 'sales ledgers',
    options: 'Sales options',
    page: 'sales-dashboard',
    register: 'Sales Register',
    notes: 'Credit Note Register',
    group: 'Sales Accounts',
  },
  purchases: {
    module: 'purchases',
    net: 'Net purchases',
    returns: 'Purchase returns',
    party: 'Vendor',
    parties: 'vendors',
    top: 'Top vendors',
    facet: 'voucher_type',
    loadError: "The purchases couldn't be loaded.",
    byMonth: 'Net purchases by month',
    byMonthTable: 'Purchases by month',
    mix: 'Purchases by voucher type',
    mixLabel: 'Net purchases by voucher type',
    ledgers: 'purchase ledgers',
    options: 'Purchases options',
    page: 'purchases-dashboard',
    register: 'Purchase Register',
    notes: 'Debit Note Register',
    group: 'Purchase Accounts',
  },
}
