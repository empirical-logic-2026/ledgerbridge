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
