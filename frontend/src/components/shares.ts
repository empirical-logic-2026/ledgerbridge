// A mix's parts and their shares, for the donut (components/Donut.tsx). Pure: tested in
// shares.test.ts.

import { toScaled } from '../format.ts'

export interface DonutPart {
  name: string
  amount: string // exact decimal
  to?: string // the page behind the part
}

/** Each part's share of the positive total in percent, rounded to one decimal (0 without a total);
 *  a negative part (e.g. returns larger than sales) counts as nothing. */
export function shares(parts: DonutPart[]): number[] {
  const positive = (amount: string) => (toScaled(amount) > 0n ? toScaled(amount) : 0n)
  const total = parts.reduce((sum, p) => sum + positive(p.amount), 0n)
  return parts.map((p) => (total > 0n ? Number((positive(p.amount) * 1000n + total / 2n) / total) / 10 : 0))
}
