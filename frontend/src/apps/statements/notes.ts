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
    { text: 'Several companies are added together, without inter-company eliminations.' },
  ],
  footer: "To compare: Tally's Balance Sheet (Gateway of Tally) at the same date.",
}
