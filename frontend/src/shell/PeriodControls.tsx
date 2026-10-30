// Period controls: the financial year and the "as at" date. The dates offered are those
// the statements are stored for (month ends and year ends); with none stored in the year,
// the year's end (or today) is used and profit isn't shown.

import { Select } from 'antd'
import type { FinancialYear } from '../api/types.ts'
import { formatDate } from '../format.ts'

interface Props {
  years: FinancialYear[]
  year: FinancialYear | undefined
  dates: string[]
  asOf: string | undefined
  onYear: (startYear: number) => void
  onDate: (date: string) => void
}

export function PeriodControls({ years, year, dates, asOf, onYear, onDate }: Props) {
  const dateOptions = dates.map((d) => ({ value: d, label: `As at ${formatDate(d)}` }))
  if (asOf && !dates.includes(asOf)) dateOptions.unshift({ value: asOf, label: `As at ${formatDate(asOf)}` })
  return (
    <>
      <Select
        aria-label="Financial year"
        value={year?.start_year}
        options={years.map((y) => ({ value: y.start_year, label: y.label }))}
        onChange={onYear}
        style={{ minWidth: 120 }}
      />
      <Select
        aria-label="As at"
        value={asOf}
        options={dateOptions}
        onChange={onDate}
        style={{ minWidth: 170 }}
      />
    </>
  )
}
