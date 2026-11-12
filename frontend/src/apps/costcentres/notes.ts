// The notes at the top of the Cost centres page and a cost centre's page (components/PageNote.tsx),
// in plain words, next to these pages' labels. The same explanation, in ASD-STE100:
// docs/dashboard-pages.md.

import type { NoteContent } from '../../components/PageNote.tsx'

export const centresNote: NoteContent = {
  title: 'About this page',
  points: [
    { text: 'Every cost centre with what the vouchers allocated to it in the period, in total and month by month, and how many allocations.' },
    { text: 'The amounts come from the cost centre allocations on the voucher lines in Tally (F-CC-001, F-CC-003). An expense is positive.' },
    { text: "A cost centre's row holds only its own allocations: the centres under it have rows of their own. Tally's report adds them into the parent." },
    { text: 'A cost centre is known by its name and category across the companies you chose. Click one to see its allocations.' },
  ],
  footer: "To compare: Tally's Statements of Accounts › Cost Centres › Category Summary for the same period.",
}

export const centreNote: NoteContent = {
  title: 'About this page',
  points: [
    { text: 'One cost centre: every allocation to it in the period, with the voucher, the ledger, the category and the amount.' },
    { text: 'Each amount is one voucher line\'s allocation to this cost centre (F-CC-002); the total is the cost centre\'s figure on the list (F-CC-001).' },
    { text: 'Only this cost centre\'s own allocations are listed, not those of the centres under it.' },
    { text: 'Click a voucher number to open the voucher.' },
  ],
  footer: "To compare: the cost centre's breakup in Tally (Cost Centres › the centre) for the same period.",
}
