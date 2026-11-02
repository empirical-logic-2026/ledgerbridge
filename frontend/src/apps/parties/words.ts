// What the Customers and Vendors pages call things, and where they sit (one wording for both
// kinds of party: core/parties.py).

export type PartyKind = 'customers' | 'vendors'

export const PARTY_WORDS: Record<
  PartyKind,
  { title: string; one: string; group: string[]; net: string; balance: string; settled: string; settledOne: string; debtors: string; register: string[] }
> = {
  customers: {
    title: 'Customers',
    one: 'Customer',
    group: ['sales', 'customers'],
    net: 'Net sales',
    balance: 'Balance due',
    settled: 'Receipts',
    settledOne: 'receipt',
    debtors: 'Sundry Debtors',
    register: ['sales', 'register'],
  },
  vendors: {
    title: 'Vendors',
    one: 'Vendor',
    group: ['purchases', 'vendors'],
    net: 'Net purchases',
    balance: 'Balance payable',
    settled: 'Payments',
    settledOne: 'payment',
    debtors: 'Sundry Creditors',
    register: ['purchases', 'register'],
  },
}
