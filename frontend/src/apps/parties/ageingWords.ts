// What the Receivables and Payables pages say (apps/parties/Ageing.tsx): the bucket names, the
// parts of "not in bills" with what each means, and the "How ageing is worked out" note, in
// plain words, matching core/ageing.py. One place, so the note can't drift from the page.

import type { AgeingRowOut } from '../../api/types.ts'
import type { NoteContent } from '../../components/PageNote.tsx'
import type { PartyKind } from './words.ts'

export type Basis = 'due_date' | 'bill_date'

export const BUCKET_LABELS: [keyof AgeingRowOut['buckets'], string][] = [
  ['not_due', 'Not due'],
  ['days_1_30', '1–30 days'],
  ['days_31_60', '31–60 days'],
  ['days_61_90', '61–90 days'],
  ['days_91_180', '91–180 days'],
  ['over_180', 'Over 180 days'],
]

export const BASIS_LABELS: Record<Basis, string> = {
  due_date: 'Days past the due date',
  bill_date: 'Days since the bill date',
}

/** The parts of "Not in bills", in order, each with its formula and what it means. */
export const NOT_IN_BILLS: { key: 'on_account' | 'opening_difference' | 'revaluation' | 'other'; label: string; formula: string; meaning: string }[] = [
  { key: 'on_account', label: 'On account', formula: 'F-PTY-015', meaning: 'Amounts entered without a bill, for example a payment not set against an invoice.' },
  {
    key: 'opening_difference',
    label: 'Opening-bill difference',
    formula: 'F-PTY-016',
    meaning: "The part of a ledger's opening balance that its opening bills don't explain.",
  },
  {
    key: 'revaluation',
    label: 'Exchange-rate revaluation',
    formula: 'F-PTY-020',
    meaning: 'For a party in a foreign currency, the balance at the current rate less the balance in the books.',
  },
  { key: 'other', label: 'Other', formula: 'F-PTY-017', meaning: "Entries of ledgers that aren't kept bill by bill." },
]

/** "How ageing is worked out", for receivables or payables. */
export function ageingNote(kind: PartyKind): NoteContent {
  const who = kind === 'customers' ? 'customers owe us' : 'we owe vendors'
  const group = kind === 'customers' ? 'Sundry Debtors' : 'Sundry Creditors'
  return {
    title: 'How ageing is worked out',
    points: [
      { text: `The page shows what ${who} at the end of the period, party by party, from the bills in Tally: the opening bills and the bills of each voucher.` },
      { text: "A bill's age is the number of days past its due date. If a bill has no due date, it is due on its bill date plus the party's credit days. You can also age bills by their bill date." },
      { text: 'Bills go into six groups: not due, 1–30, 31–60, 61–90, 91–180 and over 180 days. A bill is overdue only after its due date.' },
      { text: '"Not in bills" is the part of the balance that no bill explains: amounts on account, opening-bill differences, exchange-rate revaluation of foreign-currency parties, and ledgers not kept bill by bill.' },
      { text: `The total equals the ${group} balance on Tally's Balance Sheet at the same date. Several companies are added together without inter-company eliminations.` },
    ],
    footer: `To compare: in Tally, open Statements of Accounts › Outstandings › Ageing Analysis (${kind === 'customers' ? 'Receivables' : 'Payables'}) at the same date, by due date.`,
  }
}
