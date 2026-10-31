import { describe, expect, it } from 'vitest'
import { cssVariables, tokens, type Mode } from './theme.ts'

// WCAG 2 contrast ratio between two #RRGGBB colours.
function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => {
    const c = parseInt(hex.slice(i, i + 2), 16) / 255
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
  })
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}

const AA = 4.5 // normal-size text

describe.each(['light', 'dark'] as Mode[])('the %s theme', (mode) => {
  const t = tokens[mode]
  const pairs: [string, string, string][] = [
    ['text on surface', t.text, t.surface],
    ['text on page', t.text, t.page],
    ['muted text on surface', t.muted, t.surface],
    ['muted text on page', t.muted, t.page],
    ['green figures and links on surface', t.positive, t.surface],
    ['green figures and links on page', t.positive, t.page],
    ['crimson figures on surface', t.negative, t.surface],
    ['crimson on its soft background', t.negative, t.negativeSoft],
    ['text on selected chips', t.text, t.primarySoft],
    ['green on selected chips', t.positive, t.primarySoft],
    ['white on primary buttons', '#FFFFFF', t.primary],
    ['text on the charcoal bar', t.onCharcoal, t.charcoal],
    ['muted text on the charcoal bar', t.onCharcoalMuted, t.charcoal],
  ]

  it.each(pairs)('%s meets WCAG AA', (_label, fg, bg) => {
    expect(contrast(fg, bg)).toBeGreaterThanOrEqual(AA)
  })

  it('keeps charcoal for the top bar and side panels in both modes', () => {
    expect(t.charcoal).toBe(tokens.light.charcoal)
  })

  it('becomes CSS variables', () => {
    expect(cssVariables(mode)['--lb-primary-soft']).toBe(t.primarySoft)
    expect(cssVariables(mode)['--lb-on-charcoal-muted']).toBe(t.onCharcoalMuted)
  })
})
