// The By-godown view's words (apps/stock/StockGodowns.tsx): each section's name and meaning in
// plain words, matching how Tally counts it (core/stock_godowns.py), and the link of a row.

import type { GodownRowOut } from '../../api/types.ts'
import type { Query } from '../../router.ts'
import { builtHref } from '../../shell/nav.ts'

export type SectionKey = 'ours' | 'held_for_others' | 'at_job_workers'

/** Each section's name and what it means, in plain words (shown above its table). */
export const SECTION_WORDS: Record<SectionKey, { title: string; help: string }> = {
  ours: {
    title: 'Our stock',
    help: 'Our stock in our own godowns. Included in the total.',
  },
  held_for_others: {
    title: "Others' stock held with us (not ours)",
    help:
      "Stock that belongs to others and is kept in our godowns. It isn't ours, but Tally's Stock Summary and closing stock " +
      'include it, so it is included in the total here too, and the total matches Tally.',
  },
  at_job_workers: {
    title: 'Our stock at job workers (still ours)',
    help:
      "Our stock at a job worker's godown. Tally leaves it out of its Stock Summary and closing stock, so it is not included in " +
      'the total. Tally records there only what the job worker used, so the quantity can be negative; it has no value.',
  },
}

export const NOT_SPLIT = '(opening, not split by godown)'

/** The item's page at that godown. */
export function godownHref(row: GodownRowOut, query: Query): string | undefined {
  return builtHref(['stock', 'summary', String(row.item_id)], row.godown ? { ...query, godown: [row.godown] } : query)
}

/** The "How this page divides stock" note at the top of the By godown page: one point per
 *  section, under the section's own title, then how the total and the values are worked out. */
export const DIVIDES_STOCK = {
  title: 'How this page divides stock',
  points: [
    { section: 'ours' as SectionKey, text: 'Stock we hold in our own locations. Counted in the total.' },
    {
      section: 'held_for_others' as SectionKey,
      text: "Goods that belong to someone else but are kept in our godowns. Tally counts them in its Stock Summary, so we count them in the total too.",
    },
    {
      section: 'at_job_workers' as SectionKey,
      text:
        'Material we sent out for processing. It is still ours, but Tally keeps it at the godown it was sent from and records here only ' +
        'what the job worker used. That is why it can show a negative quantity, and why it is not added to the total.',
    },
  ],
  footer:
    "The total on this page equals Tally's Stock Summary for the same date. Values per godown are worked out at each item's rate; " +
    "Tally's own value for each godown is shown beside them.",
}

const NOTE_KEY = 'ledgerbridge.godownNote' // "closed" once the reader closes it; this browser only

/** Whether the note starts open: open the first time, then as the reader last left it. */
export function noteStartsOpen(): boolean {
  try {
    return window.localStorage.getItem(NOTE_KEY) !== 'closed'
  } catch {
    return true // storage blocked: open
  }
}

/** Remembers whether the reader left the note open (in this browser only). */
export function rememberNote(open: boolean): void {
  try {
    if (open) window.localStorage.removeItem(NOTE_KEY)
    else window.localStorage.setItem(NOTE_KEY, 'closed')
  } catch {
    // storage blocked: the note opens again next time
  }
}
