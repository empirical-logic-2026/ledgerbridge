// A waterfall's bars (components/Waterfall.tsx): the opening and closing as whole bars from
// zero, each movement as a bar floating from the running total. Pure, on exact amounts: tested
// in waterfall.test.ts. Heights in lakhs are for drawing only (F-FMT-003).

import { toLakhs, toScaled } from '../format.ts'
import { fromScaled } from '../reporting/explorer.ts'

export interface Step {
  label: string
  amount: string // exact decimal: the total (first and last) or the movement
}

export interface WaterfallBar {
  label: string
  base: number // where the bar starts, lakhs
  height: number // its length, lakhs (never negative)
  kind: 'total' | 'up' | 'down'
  amount: string // exact, as given
}

/** The bars from the opening (first step) through the movements to the closing (last step). */
export function waterfallBars(steps: Step[]): WaterfallBar[] {
  if (steps.length < 2) return []
  const [opening, ...rest] = steps
  const closing = rest.pop() as Step
  const bars: WaterfallBar[] = [{ label: opening.label, base: 0, height: toLakhs(opening.amount), kind: 'total', amount: opening.amount }]
  let running = toScaled(opening.amount)
  for (const step of rest) {
    const move = toScaled(step.amount)
    const after = running + move
    const low = move >= 0n ? running : after
    bars.push({ label: step.label, base: toLakhs(fromScaled(low)), height: Math.abs(toLakhs(step.amount)), kind: move >= 0n ? 'up' : 'down', amount: step.amount })
    running = after
  }
  bars.push({ label: closing.label, base: 0, height: toLakhs(closing.amount), kind: 'total', amount: closing.amount })
  return bars
}
