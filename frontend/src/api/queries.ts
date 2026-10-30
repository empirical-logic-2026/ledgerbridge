// The API's data for the dashboard, cached by TanStack Query (one hook per endpoint).

import { useQuery } from '@tanstack/react-query'
import { getJson } from './client.ts'
import type { Company, Overview, Periods } from './types.ts'

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

export function useOverview(companies: number[] | undefined, fy: number | undefined, asOf: string | undefined) {
  return useQuery({
    queryKey: ['overview', companies, fy, asOf],
    queryFn: () =>
      getJson<Overview>('/api/v1/overview', { company: companies, financial_year: fy, as_of: asOf }),
    enabled: companies !== undefined && companies.length > 0 && fy !== undefined,
  })
}
