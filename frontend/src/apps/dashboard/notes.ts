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
    { text: "The Profit & Loss A/c as Tally shows it: two sides, the gross block with Gross Profit (or Loss) c/o and b/f, then the net block with Nett Profit (or Loss) and the Totals, equal on both sides (F-PL-011 to F-PL-014, F-PL-017)." },
    { text: 'Each group sits on the side of its balance for the period: a debit on the left, a credit on the right, as Tally places it (so a direct expense in credit is on the right). Click a group to see its ledgers.' },
    { text: "Every amount comes from our statements, checked against Tally's own: the statement at the end of the period less the one before its start (F-PL-007). The end must be a stored statement date: Tally's closing stock exists only there." },
    { text: 'Above it: the margins, the cost structure and the months (F-PL-005, F-PL-006, F-PL-008, F-PL-010). The Analysis view shows companies, months or quarters as columns with % of sales.' },
    { text: 'Several companies: one column each and a total, added without inter-company eliminations. In Educational mode, a month ending on the 30th runs to the 2nd of the next month.' },
  ],
  footer: "To compare: Tally's Profit & Loss A/c (Gateway of Tally) for the same company and period (F2).",
}

// The Profit & Loss in Tally's layout (ADR-056): its labels.
export const PL_TALLY_WORDS = {
  left: 'Profit & Loss A/c, left side (debit)',
  right: 'Profit & Loss A/c, right side (credit)',
  noEnd: "No Profit & Loss in Tally's layout for this period",
  nearest: 'Choose a stored statement date as the end:',
  endOn: (day: string) => `End on ${day}`,
  openAll: 'Open every group',
  drillNote: "Each level adds up to the line; a ledger on the other side shows a negative amount. Click a ledger to see its statement.",
  how: "As Tally places them: a group on the side of its balance, a group with nothing in the period on its usual side, without an amount. Click a group to see its ledgers, or a stock line to see the stock.",
  tally: "Tally's layout",
  analysis: 'Analysis view',
}
