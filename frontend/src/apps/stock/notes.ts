// The notes at the top of the Stock summary, the By godown page and an item's page
// (components/PageNote.tsx), in plain words, next to these pages' labels (godownWords.ts). The
// same explanation, in ASD-STE100: docs/dashboard-pages.md.

import type { NoteContent } from '../../components/PageNote.tsx'
import { DIVIDES_STOCK, SECTION_WORDS } from './godownWords.ts'

export const stockNote: NoteContent = {
  title: 'About this page',
  points: [
    { text: "Every stock item with its opening, inward, outward and closing quantity, its value and rate, and the stock value by date, stock group and godown." },
    { text: 'Quantities are ours, worked out from the vouchers in Tally and checked against Tally item by item (F-STK-001 to F-STK-004).' },
    { text: "Values are Tally's own (its valuation method), at the last stored statement date in the period, which can be before its end (F-STK-005 to F-STK-007)." },
    { text: "Stock at a job worker's godown is left out, as Tally leaves it out: see the By godown page." },
  ],
  footer: "To compare: Tally's Stock Summary (Gateway of Tally) at the same date.",
}

/** "How this page divides stock": one point per section, under its own title. */
export const godownsNote: NoteContent = {
  title: DIVIDES_STOCK.title,
  points: DIVIDES_STOCK.points.map((p) => ({ label: SECTION_WORDS[p.section].title, text: p.text })),
  footer: `${DIVIDES_STOCK.footer} To compare: Tally's Stock Summary and Godown Summary at the same date.`,
}

export const itemNote: NoteContent = {
  title: 'About this page',
  points: [
    { text: "One stock item: its closing quantity, value and rate, every movement with the quantity after it, each month, and where it is by godown and batch." },
    { text: "Quantities come from the vouchers in Tally (F-STK-001 to F-STK-004); values are Tally's own at the last stored statement date in the period (F-STK-005)." },
    { text: 'A movement\'s "Other godown" is where the stock went, or where it came from.' },
    { text: "At one godown (a link from By godown), the movements and months are at that godown only, and a month has no value: Tally keeps none per item and godown." },
  ],
  footer: "To compare: Tally's Stock Item Monthly Summary, and the Godown Summary for one godown.",
}
