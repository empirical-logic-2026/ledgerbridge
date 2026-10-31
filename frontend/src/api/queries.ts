// The API's data for the dashboard, cached by TanStack Query (one hook per endpoint).

import { useQuery } from '@tanstack/react-query'
import { getJson } from './client.ts'
import type { PeriodChoice } from '../selection.ts'
import type { Company, Home, Periods } from './types.ts'

export function useCompanies() {
  return useQuery({
    queryKey: ['companies'],
    queryFn: () => getJson<Company[]>('/api/v1/companies'),
  })
}

export function usePeriods(companies: number[] | undefined) {
  return useQuery({
    queryKey: ['periods', companies],
    queryFn: () => getJson<Periods>('/api/v1/periods', { company: companies }),
    enabled: companies !== undefined && companies.length > 0,
  })
}

export function useHome(companies: number[] | undefined, period: PeriodChoice | undefined, compare: boolean) {
  return useQuery({
    queryKey: ['home', companies, period, compare],
    queryFn: () =>
      getJson<Home>('/api/v1/home', {
        company: companies,
        month: period?.months.length ? period.months : undefined,
        date_from: period?.months.length ? undefined : period?.from,
        date_to: period?.months.length ? undefined : period?.to,
        compare: compare ? 'true' : undefined,
      }),
    enabled: companies !== undefined && companies.length > 0 && period !== undefined,
  })
}
