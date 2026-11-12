// What the Explore page says (apps/data/Explore.tsx): its "How this page works" note, in plain
// words, next to the page so it can't drift from it.

import type { NoteContent } from '../../components/PageNote.tsx'

export const exploreNote: NoteContent = {
  title: 'How this page works',
  points: [
    { text: 'Choose a dataset: voucher lines, vouchers, cost allocations, GST lines or inventory lines. Each row comes from the books as Tally holds them.' },
    { text: 'Group by up to four columns to see a subtotal for each group and a total; without groups, you see the rows themselves.' },
    { text: 'The dates follow the period in the top bar unless you set them here. Several companies are added together without inter-company eliminations.' },
    { text: 'Each measure names its formula in its column header (for example F-TRN-001 for debits and credits).' },
    { text: 'Save a view to come back to the same choices in this browser; Export CSV gives the same result as a file, with the subtotals and the total.' },
  ],
  footer: "To compare: in Tally, open the Day Book or the register of the same vouchers for the same dates.",
}
