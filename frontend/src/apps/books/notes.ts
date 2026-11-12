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

export const ledgerPickNote: NoteContent = {
  title: 'About this page',
  points: [
    { text: "One ledger's statement for the period: find a ledger by its name, or open one from the Trial Balance, the Balance Sheet, a party's page, the Transactions page or Explore." },
    { text: 'It shows the opening balance, every entry with the other ledger, debit, credit and the running balance, and the closing balance (F-LED-001 to F-LED-004).' },
    { text: 'The figures come from the vouchers in Tally; cancelled and optional vouchers are left out.' },
  ],
  footer: "To compare: Tally's ledger report (Display More Reports → Account Books → Ledger) for the same dates.",
}

export const ledgerNote: NoteContent = {
  title: 'About this page',
  points: [
    { text: "The ledger's opening balance, each voucher of the period with the other ledger, debit, credit and the running balance, and the closing balance (F-LED-001 to F-LED-004)." },
    { text: "The opening is the ledger's balance before the period. An income or expense ledger starts each financial year at nil, as in Tally: earlier years went into Profit & Loss A/c." },
    { text: "A foreign-currency ledger gets Tally's own calculated row \"Unadjusted Forex Gain/Loss\" at the period's end, so the closing is its revalued balance." },
    { text: 'Click a voucher number to open the voucher. Cancelled and optional vouchers are left out.' },
  ],
  footer: "To compare: Tally's ledger report (Display More Reports → Account Books → Ledger) for the same dates.",
}

// The Ledger statement page's labels (ADR-055).
export const LEDGER_WORDS = {
  pick: 'Find a ledger',
  pickHelp: "Type part of the ledger's name.",
  none: 'No ledger has that name.',
  opening: 'Opening balance',
  closing: 'Closing balance',
  revaluation: 'Calculated by Tally at the end of the period (no voucher).',
  truncated: 'Only the first 5,000 entries are shown; the totals and the closing balance cover them all.',
}
