// The notes at the top of the Sales and Purchases dashboards and the Channels page
// (components/PageNote.tsx), in plain words, next to these pages' labels (words.ts). One function
// per page gives the sales or the purchase wording. The same explanation, in ASD-STE100:
// docs/dashboard-pages.md.

import type { NoteContent } from '../../components/PageNote.tsx'

export type Side = 'sales' | 'purchases'

const W = {
  sales: { what: 'sales', group: 'Sales Accounts', invoice: 'sales invoices', returns: 'credit notes', party: 'customer', register: 'Sales Register', filters: 'customer and channel' },
  purchases: { what: 'purchases', group: 'Purchase Accounts', invoice: 'purchase invoices', returns: 'debit notes', party: 'vendor', register: 'Purchase Register', filters: 'voucher type' },
}

export function dashboardNote(side: Side): NoteContent {
  const w = W[side]
  return {
    title: 'About this page',
    points: [
      { text: `The ${w.what} of the period: net ${w.what}, invoices, average invoice and returns, by month and by company, the mix by voucher type, the top ${w.party}s and the largest invoices.` },
      { text: `The figures come from the vouchers in Tally that post to the ledgers under ${w.group}, for any dates you choose; they don't need stored statements.` },
      { text: `Net ${w.what} = gross (${w.invoice}) + returns (${w.returns}, negative) + other adjustments such as journals (F-SAL-001 to F-SAL-004). Average invoice = gross ÷ invoices (F-SAL-006).` },
      { text: `The ${w.filters} filters in the header narrow every figure on the page. Several companies are added together, without inter-company eliminations.` },
    ],
    footer: `To compare: Tally's ${w.register} for the same period, and the ${w.group} line of the Profit & Loss A/c.`,
  }
}

export const channelsNote: NoteContent = {
  title: 'About this page',
  points: [
    { text: 'Net sales by channel, with a column for each month. A channel is a voucher type, for example "Sales - Online".' },
    { text: 'The figures come from the vouchers in Tally that post to the ledgers under Sales Accounts (F-SAL-009); a channel\'s share is its part of all channels (F-SAL-010).' },
    { text: 'Voucher types with the same name in two companies count as one channel. Several companies are added together, without inter-company eliminations.' },
    { text: 'Click a channel, or one of its months, to open the Sales register for it.' },
  ],
  footer: "To compare: Tally's Sales Register for the same voucher type and period.",
}
