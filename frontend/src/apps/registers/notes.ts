// The notes at the top of the Sales and Purchase registers and the Monthly sales and purchases
// pages (components/PageNote.tsx), in plain words, next to these pages' labels. The same
// explanation, in ASD-STE100: docs/dashboard-pages.md.

import type { NoteContent } from '../../components/PageNote.tsx'
import type { Side } from '../sales/notes.ts'

const W = {
  sales: { what: 'sales', group: 'Sales Accounts', vouchers: 'sales invoice and credit note', register: 'Sales Register' },
  purchases: { what: 'purchases', group: 'Purchase Accounts', vouchers: 'purchase invoice and debit note', register: 'Purchase Register' },
}

export function registerNote(side: Side): NoteContent {
  const w = W[side]
  return {
    title: 'About this page',
    points: [
      { text: `Every ${w.vouchers} of the period, as Tally's Day Book shows them, grouped by month with subtotals.` },
      { text: 'Debit and credit are the first ledger line of the voucher, usually the party (F-REG-001).' },
      { text: `Value is only the voucher's lines on the ledgers under ${w.group}: taxes and freight on other ledgers aren't in it (F-REG-002). A return is negative.` },
      { text: 'Cancelled and optional vouchers are left out. Click a voucher number to open the voucher.' },
    ],
    footer: `To compare: Tally's ${w.register} for the same period.`,
  }
}

export function monthlyNote(side: Side): NoteContent {
  const w = W[side]
  return {
    title: 'About this page',
    points: [
      { text: `Each month's gross ${w.what}, returns, other adjustments and net ${w.what}, with the number of invoices.` },
      { text: `The figures come from the vouchers in Tally that post to the ledgers under ${w.group} (F-SAL-001 to F-SAL-005).` },
      { text: "The closing balance adds the net from the start of each company's own financial year to the end of the month (F-SAL-008)." },
      { text: 'Click a month to open its register. Several companies are added together, without inter-company eliminations.' },
    ],
    footer: `To compare: Tally's Group Summary of ${w.group}, month by month (the Closing Balance column).`,
  }
}
