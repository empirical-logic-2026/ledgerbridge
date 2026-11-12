// The note at the top of the Cash movement page (components/PageNote.tsx), in plain words, next to
// the page's labels. The same explanation, in ASD-STE100: docs/dashboard-pages.md.

import type { NoteContent } from '../../components/PageNote.tsx'

export const cashFlowNote: NoteContent = {
  title: 'About this page',
  points: [
    { text: 'Cash and bank at the start and the end of the period, the money in and out by what it was for, and each month.' },
    { text: 'The figures come from the vouchers in Tally on the Cash-in-Hand and Bank Accounts ledgers: the start plus money in less money out is the end, exactly (F-CF-001, F-BAL-002).' },
    { text: "Each amount goes to the category of the voucher's other ledgers: customers, suppliers, income, expenses, taxes, loans, capital, assets or other." },
    { text: 'A move between cash and bank is a transfer and adds nothing. Bank OD accounts are loans, so they are not cash here.' },
  ],
  footer: "To compare: Tally's Cash/Bank Book(s) (Display More Reports › Account Books) for the same period.",
}
