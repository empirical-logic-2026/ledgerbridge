// The note at the top of the Balance Sheet (components/PageNote.tsx), in plain words, next to the
// page's labels. The same explanation, in ASD-STE100: docs/dashboard-pages.md.

import type { NoteContent } from '../../components/PageNote.tsx'

export const balanceSheetNote: NoteContent = {
  title: 'About this page',
  points: [
    { text: 'The Balance Sheet at the end of the period, beside the end of the comparison period, with the change, and the ratios as tiles.' },
    { text: "The lines come from our Balance Sheet, built from the books and checked line by line against Tally's, at the last stored statement date in the period (F-BS-005)." },
    { text: "Current assets and liabilities in the ratios follow Schedule III: each ledger on the side of its balance, Bank OD and banks in credit as short-term borrowings (F-RAT-008 to F-RAT-010). Hover a ratio to see its parts." },
    { text: "So the ratios can differ from Tally's Ratio Analysis, which nets each group. In Educational mode, a month ending on the 30th uses the 2nd of the next month." },
    { text: 'Several companies are added together, without inter-company eliminations. Click a line to see its groups and ledgers at the date (F-BS-012).' },
  ],
  footer: "To compare: Tally's Balance Sheet (Gateway of Tally) at the same date.",
}

// The Balance Sheet's drill-down (ADR-055): what a line's rows are.
export const DRILL_WORDS = {
  title: (line: string, date: string) => `${line} at ${date}`,
  help: 'Click a line of the Balance Sheet to see its groups and ledgers at the date. Open a group to go down; click a ledger to see its statement.',
  close: 'Close',
  revaluation: "The stored Balance Sheet takes this group from Tally (foreign-currency ledgers); the gap is shown as its own row so the rows add up.",
}

// The Trial Balance page (ADR-055): its labels, help and note.
export const TB_WORDS = {
  asAt: 'At',
  yearFrom: 'for the financial year from',
  booksBeginning: "the books' beginning",
  settingsMissing:
    'Run the statements once more (./dev.ps1 statements): the groups Tally nets for reporting and the profit of earlier years are read with them. Until then those lines may differ from Tally.',
  unproved: "The difference in opening balances is shown as Tally's screen shows it; Tally's exported Trial Balance has no such line, so it is not yet proved against Tally.",
  help:
    "Every group with its debit or credit balance at the period's statement date, for the financial year that date falls in, as Tally opens its Trial Balance (F-TB-001, F-TB-002). Income and expenses count only this financial year (F-TB-003); the stock is the year's opening stock (F-TB-004); Profit & Loss A/c adds the profit of earlier years (F-TB-005).",
  compare: 'Gateway of Tally → Display More Reports → Trial Balance for the same financial year to the same date; Alt+F1 for the detailed view.',
}

export const trialBalanceNote: NoteContent = {
  title: 'About this page',
  points: [
    { text: "Every group with its debit or credit at the period's statement date, and the totals, as Tally's Trial Balance shows them (F-TB-001, F-TB-002). Detailed opens each group to its sub-groups and ledgers; click a ledger to see its statement." },
    { text: 'It covers the financial year the date falls in, as Tally opens it: income and expenses of this year only (F-TB-003), the stock at the start of the year (F-TB-004), and Profit & Loss A/c with the profit of earlier years (F-TB-005).' },
    { text: "So after a year end it differs from our stored statements, which run from the books' beginning, and equals what Tally shows for the year." },
    { text: 'A group Tally nets for reporting is one figure; the others split ledger by ledger into debit and credit, as in Tally.' },
    { text: 'Several companies are added together, without inter-company eliminations.' },
  ],
  footer: "To compare: Tally's Trial Balance (Display More Reports) for the same financial year to the same date; Alt+F1 for the detailed view.",
}
