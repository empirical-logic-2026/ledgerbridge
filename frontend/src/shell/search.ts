// What a search holds (the search bar edits it; each list decides what it means).

export interface FilterChoice {
  value: string
  label: string
}

export interface FilterOption {
  key: string
  label: string
  choices: FilterChoice[]
}

export interface GroupOption {
  key: string
  label: string
}

export interface ActiveFilter {
  key: string
  value: string
  label: string // "Voucher type: Sales"
}

export interface SearchState {
  text: string
  filters: ActiveFilter[]
  groupBy: string[]
}

export const EMPTY_SEARCH: SearchState = { text: '', filters: [], groupBy: [] }
