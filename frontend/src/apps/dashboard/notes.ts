// The notes at the top of the Overview and the Profit & Loss page (components/PageNote.tsx), in
// plain words, next to these pages' labels: what the page shows, where the figures come from,
// how they are worked out (formula IDs: docs/formula-sheet.md), what could surprise, and the
// Tally report to compare with. The same explanation, in ASD-STE100: docs/dashboard-pages.md.

import type { NoteContent } from '../../components/PageNote.tsx'

export const overviewNote: NoteContent = {
  title: 'About this page',
  points: [
    { text: 'The whole business at a glance: net sales, gross and net profit, cash and bank, customers, sales and purchases by month, sales by channel, the Profit & Loss against last year and the top customers.' },
    { text: 'Sales, purchases and customers come from the vouchers in Tally for the period (F-SAL-004, F-PUR-001, F-SAL-011). Cash and bank is the balance at the end of the period (F-BAL-002).' },
    { text: "Profit comes from our Profit & Loss statements, built from the books and checked against Tally's (F-PL-003, F-PL-004). It runs to the last stored statement date in the period, and the page says so." },
    { text: "In Tally's Educational mode, a month ending on the 30th (or in February) runs to the 2nd of the next month, because Tally only allows those dates." },
    { text: 'Several companies are added together, without inter-company eliminations.' },
  ],
  footer: "To compare: Tally's Profit & Loss A/c and Sales Register for the same period, and the Balance Sheet for cash and bank.",
}

export const profitLossNote: NoteContent = {
  title: 'About this page',
  points: [
    { text: 'The margins, the cost structure, net sales and profit by month, and the full Profit & Loss with the comparison period and the change.' },
    { text: "Every line comes from our Profit & Loss statements, built from the books and checked line by line against Tally's own: the statement at the end of the period less the one before its start (F-PL-007)." },
    { text: 'Gross margin and net profit % are profit as a share of net sales (F-PL-005, F-PL-006); the cost structure shows each cost as a share of net sales (F-PL-008, F-PL-010).' },
    { text: '"Matches Tally" shows only when every compared line is equal to Tally\'s at the dates used (F-CHK-001 to F-CHK-003).' },
    { text: 'Profit needs the statements stored for those dates (./dev.ps1 statements). In Educational mode, a month ending on the 30th runs to the 2nd of the next month.' },
  ],
  footer: "To compare: Tally's Profit & Loss A/c (Gateway of Tally) for the same company and period.",
}
