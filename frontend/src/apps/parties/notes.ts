// The notes at the top of the Customers and Vendors lists and a customer's or vendor's page
// (components/PageNote.tsx), in plain words, next to these pages' labels (words.ts). The
// Receivables and Payables notes are in ageingWords.ts. The same explanation, in ASD-STE100:
// docs/dashboard-pages.md.

import type { NoteContent } from '../../components/PageNote.tsx'
import type { PartyKind } from './words.ts'

const W = {
  customers: { one: 'customer', what: 'sales', group: 'Sundry Debtors', paid: 'receipts' },
  vendors: { one: 'vendor', what: 'purchases', group: 'Sundry Creditors', paid: 'payments' },
}

export function partiesNote(kind: PartyKind): NoteContent {
  const w = W[kind]
  return {
    title: 'About this page',
    points: [
      { text: `Every ${w.one} with ${w.what} in the period: net ${w.what}, invoices, the last invoice and the balance due at the end of the period.` },
      { text: `Net ${w.what} come from the vouchers in Tally (F-SAL-012); the balance due is the ${w.one}'s ledgers at the end of the period (F-PTY-001).` },
      { text: `A ${w.one} is known by name across the companies you chose: the same name in two companies is one row.` },
      { text: `Click a ${w.one} to open their page.` },
    ],
    footer: `To compare: the ${w.one}'s ledger in Tally (Account Books › Ledger), under ${w.group}.`,
  }
}

export function partyNote(kind: PartyKind): NoteContent {
  const w = W[kind]
  return {
    title: 'About this page',
    points: [
      { text: `One ${w.one}: the balance due, what is overdue, net ${w.what}, the average days to pay, and tabs for the invoices, ${w.paid}, the ledger statement, the outstanding bills and each month.` },
      { text: `The balance is the ${w.one}'s ledgers at the end of the period (F-PTY-001). Bills come from the opening bills and the bills of each voucher in Tally, with their due dates (F-PTY-004).` },
      { text: 'Overdue is the bills past their due date (F-PTY-002). A bill without a due date is due on its bill date plus the credit days.' },
      { text: 'Amounts entered "on account" are not bills, so the bills can add up to less than the balance (F-PTY-013).' },
      { text: `The ${w.one} is known by name across the companies you chose.` },
    ],
    footer: "To compare: Tally's ledger of the party (Account Books › Ledger) and Outstandings › Ledger.",
  }
}
