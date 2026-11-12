// The notes at the top of the Transactions page and a voucher's page (components/PageNote.tsx), in
// plain words, next to these pages' labels. The same explanation, in ASD-STE100:
// docs/dashboard-pages.md.

import type { NoteContent } from '../../components/PageNote.tsx'

export const transactionsNote: NoteContent = {
  title: 'About this page',
  points: [
    { text: 'Every ledger line of the period, one row per line, with its voucher, ledger, debit or credit, party, narration and more columns you can show.' },
    { text: "The lines come from the vouchers in Tally. A line's amount is a debit when positive and a credit when negative (F-TRN-001)." },
    { text: "Cancelled and optional vouchers are left out, as they don't change the books. The UTR is kept but not shown." },
    { text: 'Filter, group, sort or export the table; click a voucher number to open the voucher.' },
  ],
  footer: "To compare: Tally's Day Book (Display More Reports) for the same dates, with details (Alt+F1).",
}

export const voucherNote: NoteContent = {
  title: 'About this page',
  points: [
    { text: 'One voucher as Tally keeps it: its date, type, number, party, reference and narration, its ledger lines, its bills and its stock lines.' },
    { text: 'The debits and the credits of its lines are equal (F-VCH-001).' },
    { text: "A cancelled voucher has no lines; an optional one doesn't change the books. The page says when either is so." },
    { text: 'Click a stock item to open its page.' },
  ],
  footer: "To compare: open the same voucher from Tally's Day Book at its date.",
}
