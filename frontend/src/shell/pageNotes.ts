// Which note each page shows at its top (components/PageNote.tsx): the text lives in each
// module's notes.ts, next to the page's labels; this only connects a page's path to it. Every
// built page of the navigation (shell/nav.ts) and every detail page has one: App.test.tsx fails
// otherwise. App.tsx puts the note above the page.

import type { NoteContent } from '../components/PageNote.tsx'
import { overviewNote, profitLossNote } from '../apps/dashboard/notes.ts'
import { channelsNote, dashboardNote } from '../apps/sales/notes.ts'
import { monthlyNote, registerNote } from '../apps/registers/notes.ts'
import { partiesNote, partyNote } from '../apps/parties/notes.ts'
import { ageingNote } from '../apps/parties/ageingWords.ts'
import { centreNote, centresNote } from '../apps/costcentres/notes.ts'
import { balanceSheetNote } from '../apps/statements/notes.ts'
import { cashFlowNote } from '../apps/cash/notes.ts'
import { godownsNote, itemNote, stockNote } from '../apps/stock/notes.ts'
import { transactionsNote, voucherNote } from '../apps/books/notes.ts'
import { companiesNote, healthNote } from '../apps/data/notes.ts'
import { exploreNote } from '../apps/data/exploreWords.ts'

/** "<module>/<page>" -> its note; and the note of the page of one of its rows (".../<id>"). */
const NOTES: Record<string, { list: NoteContent; detail?: NoteContent }> = {
  'overview/dashboard': { list: overviewNote },
  'sales/dashboard': { list: dashboardNote('sales') },
  'sales/register': { list: registerNote('sales') },
  'sales/monthly': { list: monthlyNote('sales') },
  'sales/channels': { list: channelsNote },
  'sales/customers': { list: partiesNote('customers'), detail: partyNote('customers') },
  'purchases/dashboard': { list: dashboardNote('purchases') },
  'purchases/register': { list: registerNote('purchases') },
  'purchases/monthly': { list: monthlyNote('purchases') },
  'purchases/vendors': { list: partiesNote('vendors'), detail: partyNote('vendors') },
  'pnl/profit-loss': { list: profitLossNote },
  'pnl/cost-centres': { list: centresNote, detail: centreNote },
  'balance-sheet/statement': { list: balanceSheetNote },
  'stock/summary': { list: stockNote, detail: itemNote },
  'stock/godowns': { list: godownsNote },
  'cash-flow/movement': { list: cashFlowNote },
  'parties/receivables': { list: ageingNote('customers') },
  'parties/payables': { list: ageingNote('vendors') },
  'books/transactions': { list: transactionsNote },
  'books/vouchers': { list: voucherNote }, // a detail page: always opened with an id
  'data/health': { list: healthNote },
  'data/explore': { list: exploreNote },
  'data/companies': { list: companiesNote },
}

/** The pages that open one row ("#/sales/customers/12"): their note is the `detail` one. */
const DETAIL_PAGES = new Set(['books/vouchers'])

export interface PageNoteFor {
  page: string // the note's key in this browser: "sales-customers", "sales-customers-page"
  note: NoteContent
}

/** The note of a page, by its module and page and whether it opens one row; undefined for a
 *  page with no note (App.test.tsx fails on a built page without one). */
export function pageNoteFor(at: string, withId: boolean): PageNoteFor | undefined {
  const found = NOTES[at]
  if (!found || (DETAIL_PAGES.has(at) && !withId)) return undefined // a voucher page needs its id
  const detail = withId && !DETAIL_PAGES.has(at)
  const note = detail ? found.detail : found.list
  if (!note) return undefined
  return { page: `${at.replace('/', '-')}${detail ? '-page' : ''}`, note }
}

/** Every page with a note, for the tests: "<module>/<page>", and the detail ones with "/:id". */
export function pagesWithNotes(): string[] {
  return Object.entries(NOTES).flatMap(([at, n]) => [at, ...(n.detail ? [`${at}/:id`] : [])])
}
