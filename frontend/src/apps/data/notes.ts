// The notes at the top of the Data health and Companies pages (components/PageNote.tsx), in plain
// words, next to these pages' labels. Explore's note is in exploreWords.ts. The same
// explanation, in ASD-STE100: docs/dashboard-pages.md.

import type { NoteContent } from '../../components/PageNote.tsx'

export const healthNote: NoteContent = {
  title: 'About this page',
  points: [
    { text: 'Whether the data is complete and correct: for each company, the last sync, the result of its checks and whether Tally had it loaded.' },
    { text: "The checks compare our figures with Tally's own: vouchers, balances, statements and stock (F-DAT-002). \"Loaded in the source\" is what Tally said when last asked (F-DAT-003)." },
    { text: 'The checks are as of the date shown; a sync later in the day may not be checked yet.' },
    { text: "Companies on hold aren't shown here or on any other page." },
  ],
  footer: 'To compare: run ./dev.ps1 report for the full health report, and press F3 in Tally to see the loaded companies.',
}

export const companiesNote: NoteContent = {
  title: 'About this page',
  points: [
    { text: 'Every company the dashboard shows: its name, code, the start of its books, the first month of its financial year and its source.' },
    { text: "These come from the companies in Tally, as last synced. The name shown can be a configured display name, not Tally's own." },
    { text: "Companies on hold aren't listed." },
  ],
  footer: "To compare: press F3 (Select Company) in Tally.",
}
