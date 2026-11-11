// Pulse loading and the error state (docs/design/dashboard.md Section 0.5): the placeholders
// show only after 150 ms, the loading area is announced (aria-busy, "Loading…"), reduced motion
// stops every pulse, and Retry asks again.

import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
// The stylesheet as written (jsdom doesn't apply it; vite.config.ts lets the tests read it).
import css from '../../index.css?raw'
import { SHOW_AFTER_MS } from './delay.ts'
import { ErrorState } from './ErrorState.tsx'
import { Loading, type PageShape } from './Loading.tsx'

describe('the loading placeholders', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('lays the shape out at once but shows it only after 150 ms, so a quick load does not flicker', () => {
    const { container } = render(<Loading shape="dashboard" />)
    const shapes = container.querySelector('.loading-shapes')
    expect(shapes).not.toBeNull()
    expect(container.querySelectorAll('.pulse').length).toBeGreaterThan(0) // the layout is there
    expect(shapes).not.toHaveClass('shown')
    act(() => vi.advanceTimersByTime(SHOW_AFTER_MS - 1))
    expect(shapes).not.toHaveClass('shown')
    act(() => vi.advanceTimersByTime(1))
    expect(shapes).toHaveClass('shown')
    expect(SHOW_AFTER_MS).toBe(150)
  })

  it('marks the area busy and says "Loading…" to screen readers, hiding the shapes from them', () => {
    render(<Loading shape="report" />)
    const area = screen.getByTestId('loading')
    expect(area).toHaveAttribute('aria-busy', 'true')
    const text = screen.getByText('Loading…')
    expect(text).toHaveClass('sr-only')
    expect(text).toHaveAttribute('aria-live', 'polite')
    expect(area.querySelector('.loading-shapes')).toHaveAttribute('aria-hidden', 'true')
  })

  it.each<[PageShape, string]>([
    ['overview', '.kpi-card'],
    ['dashboard', '.kpi-card'],
    ['statement', '.ratio-tile'],
    ['kpis-report', '.ratio-tile'],
    ['chart-report', '.skeleton-table'],
    ['report', '.skeleton-table'],
  ])('draws the %s shape from the components\' own shapes', (shape, part) => {
    const { container } = render(<Loading shape={shape} />)
    expect(container.querySelector(part)).not.toBeNull()
  })

  it('draws key cards in the Overview\'s grid of five', () => {
    const { container } = render(<Loading shape="overview" />)
    expect(container.querySelectorAll('.home-kpis .kpi-card')).toHaveLength(5)
  })
})

/** The rules inside `@media (prefers-reduced-motion: reduce) { ... }`. */
function reducedMotionRules(stylesheet: string): string {
  const start = stylesheet.indexOf('@media (prefers-reduced-motion: reduce)')
  expect(start).toBeGreaterThanOrEqual(0)
  let depth = 0
  for (let i = stylesheet.indexOf('{', start); i < stylesheet.length; i++) {
    if (stylesheet[i] === '{') depth++
    if (stylesheet[i] === '}' && --depth === 0) return stylesheet.slice(start, i + 1)
  }
  throw new Error('unclosed @media block')
}

describe('reduced motion', () => {
  // jsdom doesn't apply media queries, so the stylesheet itself is checked: every selector that
  // animates is stopped under "prefers-reduced-motion: reduce" (a static placeholder).
  it('stops every animation in the stylesheet', () => {
    const uncommented = css.replace(/\/\*[\s\S]*?\*\//g, '')
    const rules = [...uncommented.matchAll(/([^{}]+)\{([^{}]*)\}/g)] // the innermost rules: [, selector, body]
    const animated = rules
      .filter(([, , body]) => /\banimation:\s*(?!none\b)\S/.test(body))
      .flatMap(([, selector]) => selector.split(',').map((part: string) => part.trim()))
    expect(animated).toEqual(expect.arrayContaining(['.pulse', '.logo-pulse']))
    const reduced = reducedMotionRules(css)
    for (const selector of animated) expect(reduced).toContain(selector)
    expect(reduced).toMatch(/\.pulse,\s*\.logo-pulse\s*\{\s*animation:\s*none;/)
  })

  it('pulses in the theme\'s colours, so it follows light and dark mode', () => {
    const keyframes = css.slice(css.indexOf('@keyframes lb-pulse'), css.indexOf('@keyframes lb-logo-pulse'))
    expect(keyframes).toContain('var(--lb-border)')
    expect(keyframes).toContain('var(--lb-primary-soft)')
    expect(keyframes).not.toMatch(/#[0-9a-f]{3,6}/i) // no fixed colours
  })
})

describe('the error state', () => {
  it('says what failed and why, and Retry asks again, showing it is busy', () => {
    const onRetry = vi.fn()
    const error = new Error('Request failed: 500')
    const { rerender } = render(<ErrorState message="The Balance Sheet couldn't be loaded." error={error} onRetry={onRetry} />)
    const alert = screen.getByRole('alert')
    expect(alert).toHaveTextContent("The Balance Sheet couldn't be loaded.")
    expect(alert).toHaveTextContent('Request failed: 500')
    const button = screen.getByRole('button', { name: /Retry/ })
    fireEvent.click(button)
    expect(onRetry).toHaveBeenCalledTimes(1)
    expect(button).toHaveClass('ant-btn-loading')
    // The retry failed again: a new error, so the button is ready for another try.
    rerender(<ErrorState message="The Balance Sheet couldn't be loaded." error={new Error('Request failed: 503')} onRetry={onRetry} />)
    expect(screen.getByRole('alert')).toHaveTextContent('Request failed: 503')
    expect(screen.getByRole('button', { name: /Retry/ })).not.toHaveClass('ant-btn-loading')
  })

  it('has no Retry when there is nothing to ask again', () => {
    render(<ErrorState message="Something couldn't be loaded." error={new Error('x')} />)
    expect(screen.queryByRole('button', { name: 'Retry' })).toBeNull()
  })
})
