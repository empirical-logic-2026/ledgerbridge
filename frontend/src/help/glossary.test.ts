import { describe, expect, it } from 'vitest'
import { explain, GLOSSARY } from './glossary.ts'

describe('the hover explanations', () => {
  it('say what a figure means, its formula and its ID in the formula sheet', () => {
    expect(explain('Average invoice')).toBe('Gross sales per invoice. = Gross ÷ Invoices (F-SAL-006)')
    expect(explain('Status')).toMatch(/"Overdue" when any of the party's bills is past its due date/)
  })

  it('name only formula IDs written as in docs/formulas.md', () => {
    for (const [label, e] of Object.entries(GLOSSARY)) {
      if (e.id) expect(e.id, label).toMatch(/^F-[A-Z]{2,3}-\d{3}$/)
      expect(e.text.length, label).toBeGreaterThan(10)
    }
  })

  it('leave a label without an explanation plain', () => {
    expect(explain('Vch No.')).toBeUndefined()
  })
})
