// The API's data for the dashboard, cached by TanStack Query (one hook per endpoint).

import { useQuery } from '@tanstack/react-query'
import { getJson } from './client.ts'
import { comparisonQuery, type CompareKind, type PeriodChoice } from '../selection.ts'
import type { AgeingOut, BalanceSheetReport, CashFlowOut, CentrePageOut, CentresOut, ChannelsOut, Company, Home, MonthlyOut, PartiesOut, PartyOut, Periods, RegisterOut, SalesDashboard, StatementReport, StockGodownsOut, StockItemPageOut, StockOut, TransactionsOut } from './types.ts'

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

export function useHome(companies: number[] | undefined, period: PeriodChoice | undefined, compare: CompareKind) {
  return useQuery({
    queryKey: ['home', companies, period, compare],
    queryFn: () =>
      getJson<Home>('/api/v1/home', {
        company: companies,
        month: period?.months.length ? period.months : undefined,
        date_from: period?.months.length ? undefined : period?.from,
        date_to: period?.months.length ? undefined : period?.to,
        ...comparisonQuery(compare, period),
      }),
    enabled: companies !== undefined && companies.length > 0 && period !== undefined,
  })
}

export function useProfitLoss(companies: number[] | undefined, period: PeriodChoice | undefined, view: string, compare: CompareKind) {
  return useQuery({
    queryKey: ['profit-loss', companies, period, view, compare],
    queryFn: () =>
      getJson<StatementReport>('/api/v1/reports/profit-loss', {
        company: companies,
        month: period?.months.length ? period.months : undefined,
        date_from: period?.months.length ? undefined : period?.from,
        date_to: period?.months.length ? undefined : period?.to,
        view,
        ...comparisonQuery(compare, period),
      }),
    enabled: companies !== undefined && companies.length > 0 && period !== undefined,
  })
}

/** The cash movement: cash and bank at the start and end, money in and out by category. */
export function useCashFlow(companies: number[] | undefined, period: PeriodChoice | undefined) {
  return useQuery({
    queryKey: ['cash-flow', companies, period],
    queryFn: () => getJson<CashFlowOut>('/api/v1/cash-flow', { company: companies, ...periodQuery(period) }),
    enabled: companies !== undefined && companies.length > 0 && period !== undefined,
  })
}

/** The Balance Sheet at the period's end, beside the comparison period's, with the ratios. */
export function useBalanceSheet(companies: number[] | undefined, period: PeriodChoice | undefined, compare: CompareKind) {
  return useQuery({
    queryKey: ['balance-sheet', companies, period, compare],
    queryFn: () => getJson<BalanceSheetReport>('/api/v1/reports/balance-sheet', { company: companies, ...periodQuery(period), ...comparisonQuery(compare, period) }),
    enabled: companies !== undefined && companies.length > 0 && period !== undefined,
  })
}

/** Receivables (customers) or payables (vendors) with ageing, as at the period's end. */
export function useAgeing(kind: 'customers' | 'vendors', companies: number[] | undefined, period: PeriodChoice | undefined) {
  return useQuery({
    queryKey: ['ageing', kind, companies, period],
    queryFn: () => getJson<AgeingOut>(`/api/v1/ageing/${kind}`, { company: companies, ...periodQuery(period) }),
    enabled: companies !== undefined && companies.length > 0 && period !== undefined,
  })
}

/** The purchases dashboard: the same response as the sales one, for the purchase side. */
export function usePurchasesDashboard(companies: number[] | undefined, period: PeriodChoice | undefined, compare: CompareKind, voucherTypes: string[]) {
  return useQuery({
    queryKey: ['purchases-dashboard', companies, period, compare, voucherTypes],
    queryFn: () =>
      getJson<SalesDashboard>('/api/v1/purchases/dashboard', {
        company: companies,
        ...periodQuery(period),
        ...comparisonQuery(compare, period),
        voucher_type: voucherTypes.length ? voucherTypes : undefined,
      }),
    enabled: companies !== undefined && companies.length > 0 && period !== undefined,
  })
}

export function useSalesDashboard(
  companies: number[] | undefined,
  period: PeriodChoice | undefined,
  compare: CompareKind,
  facets: { customer: string[]; channel: string[] },
) {
  return useQuery({
    queryKey: ['sales-dashboard', companies, period, compare, facets],
    queryFn: () =>
      getJson<SalesDashboard>('/api/v1/sales/dashboard', {
        company: companies,
        month: period?.months.length ? period.months : undefined,
        date_from: period?.months.length ? undefined : period?.from,
        date_to: period?.months.length ? undefined : period?.to,
        ...comparisonQuery(compare, period),
        customer: facets.customer.length ? facets.customer : undefined,
        channel: facets.channel.length ? facets.channel : undefined,
      }),
    enabled: companies !== undefined && companies.length > 0 && period !== undefined,
  })
}

export function useRegister(
  side: 'sales' | 'purchases',
  companies: number[] | undefined,
  period: PeriodChoice | undefined,
  facets: { party: string[]; voucherType: string[] },
) {
  return useQuery({
    queryKey: ['register', side, companies, period, facets],
    queryFn: () =>
      getJson<RegisterOut>(`/api/v1/registers/${side}`, {
        company: companies,
        month: period?.months.length ? period.months : undefined,
        date_from: period?.months.length ? undefined : period?.from,
        date_to: period?.months.length ? undefined : period?.to,
        party: facets.party.length ? facets.party : undefined,
        voucher_type: facets.voucherType.length ? facets.voucherType : undefined,
      }),
    enabled: companies !== undefined && companies.length > 0 && period !== undefined,
  })
}

export function useMonthly(
  side: 'sales' | 'purchases',
  companies: number[] | undefined,
  period: PeriodChoice | undefined,
  facets: { party: string[]; voucherType: string[] },
) {
  return useQuery({
    queryKey: ['monthly', side, companies, period, facets],
    queryFn: () =>
      getJson<MonthlyOut>(`/api/v1/monthly/${side}`, {
        company: companies,
        month: period?.months.length ? period.months : undefined,
        date_from: period?.months.length ? undefined : period?.from,
        date_to: period?.months.length ? undefined : period?.to,
        party: facets.party.length ? facets.party : undefined,
        voucher_type: facets.voucherType.length ? facets.voucherType : undefined,
      }),
    enabled: companies !== undefined && companies.length > 0 && period !== undefined,
  })
}

export function useChannels(companies: number[] | undefined, period: PeriodChoice | undefined, facets: { customer: string[]; channel: string[] }) {
  return useQuery({
    queryKey: ['channels', companies, period, facets],
    queryFn: () =>
      getJson<ChannelsOut>('/api/v1/sales/channels', {
        company: companies,
        month: period?.months.length ? period.months : undefined,
        date_from: period?.months.length ? undefined : period?.from,
        date_to: period?.months.length ? undefined : period?.to,
        customer: facets.customer.length ? facets.customer : undefined,
        channel: facets.channel.length ? facets.channel : undefined,
      }),
    enabled: companies !== undefined && companies.length > 0 && period !== undefined,
  })
}

function periodQuery(period: PeriodChoice | undefined) {
  return {
    month: period?.months.length ? period.months : undefined,
    date_from: period?.months.length ? undefined : period?.from,
    date_to: period?.months.length ? undefined : period?.to,
  }
}

export function useParties(kind: 'customers' | 'vendors', companies: number[] | undefined, period: PeriodChoice | undefined) {
  return useQuery({
    queryKey: ['parties', kind, companies, period],
    queryFn: () => getJson<PartiesOut>(`/api/v1/parties/${kind}`, { company: companies, ...periodQuery(period) }),
    enabled: companies !== undefined && companies.length > 0 && period !== undefined,
  })
}

export function useParty(kind: 'customers' | 'vendors', id: string | undefined, companies: number[] | undefined, period: PeriodChoice | undefined, compare: CompareKind) {
  return useQuery({
    queryKey: ['party', kind, id, companies, period, compare],
    queryFn: () =>
      getJson<PartyOut>(`/api/v1/parties/${kind}/${id}`, { company: companies, ...periodQuery(period), ...comparisonQuery(compare, period) }),
    enabled: id !== undefined && companies !== undefined && companies.length > 0 && period !== undefined,
  })
}

export function useCostCentres(companies: number[] | undefined, period: PeriodChoice | undefined) {
  return useQuery({
    queryKey: ['cost-centres', companies, period],
    queryFn: () => getJson<CentresOut>('/api/v1/cost-centres', { company: companies, ...periodQuery(period) }),
    enabled: companies !== undefined && companies.length > 0 && period !== undefined,
  })
}

export function useCostCentre(id: string | undefined, companies: number[] | undefined, period: PeriodChoice | undefined) {
  return useQuery({
    queryKey: ['cost-centre', id, companies, period],
    queryFn: () => getJson<CentrePageOut>(`/api/v1/cost-centres/${id}`, { company: companies, ...periodQuery(period) }),
    enabled: id !== undefined && companies !== undefined && companies.length > 0 && period !== undefined,
  })
}

export function useStock(companies: number[] | undefined, period: PeriodChoice | undefined) {
  return useQuery({
    queryKey: ['stock', companies, period],
    queryFn: () => getJson<StockOut>('/api/v1/stock', { company: companies, ...periodQuery(period) }),
    enabled: companies !== undefined && companies.length > 0 && period !== undefined,
  })
}

/** Every item by godown and batch at the period's end, in three sections (core/stock_godowns.py). */
export function useStockGodowns(companies: number[] | undefined, period: PeriodChoice | undefined) {
  return useQuery({
    queryKey: ['stock-godowns', companies, period],
    queryFn: () => getJson<StockGodownsOut>('/api/v1/stock/godowns', { company: companies, ...periodQuery(period) }),
    enabled: companies !== undefined && companies.length > 0 && period !== undefined,
  })
}

export function useStockItem(id: string | undefined, companies: number[] | undefined, period: PeriodChoice | undefined, godown?: string) {
  return useQuery({
    queryKey: ['stock-item', id, companies, period, godown],
    queryFn: () => getJson<StockItemPageOut>(`/api/v1/stock/${id}`, { company: companies, ...periodQuery(period), godown }),
    enabled: id !== undefined && companies !== undefined && companies.length > 0 && period !== undefined,
  })
}

export function useTransactions(companies: number[] | undefined, period: PeriodChoice | undefined) {
  return useQuery({
    queryKey: ['transactions', companies, period],
    queryFn: () => getJson<TransactionsOut>('/api/v1/transactions', { company: companies, ...periodQuery(period) }),
    enabled: companies !== undefined && companies.length > 0 && period !== undefined,
  })
}
