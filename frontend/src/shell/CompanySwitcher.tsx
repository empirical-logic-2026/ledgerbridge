// The company switcher: each company the user may see, and "All companies (combined)" when
// there are several (added together, without inter-company eliminations). Companies on
// hold never reach the dashboard (the API leaves them out).

import { Select } from 'antd'
import type { Company } from '../api/types.ts'
import { ALL, type Selection } from '../selection.ts'

export const COMBINED_LABEL = 'All companies (combined)'
export const COMBINED_NOTE = 'combined, without inter-company eliminations'

interface Props {
  companies: Company[]
  value: Selection['company']
  onChange: (company: Selection['company']) => void
}

export function CompanySwitcher({ companies, value, onChange }: Props) {
  const options = companies.map((c) => ({ value: String(c.id), label: c.name }))
  if (companies.length > 1) {
    options.unshift({ value: ALL, label: `${COMBINED_LABEL} · ${COMBINED_NOTE}` })
  }
  const current = value === ALL && companies.length === 1 ? String(companies[0].id) : String(value)
  return (
    <Select
      aria-label="Company"
      value={current}
      options={options}
      onChange={(next: string) => onChange(next === ALL ? ALL : Number(next))}
      popupMatchSelectWidth={false}
      style={{ minWidth: 220, maxWidth: 360 }}
      labelRender={({ value: v }) =>
        v === ALL ? COMBINED_LABEL : (companies.find((c) => String(c.id) === v)?.name ?? '')
      }
    />
  )
}
