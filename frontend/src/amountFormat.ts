// The Amounts setting (docs/formula-sheet.md F-FMT-001, F-FMT-002): every amount the dashboard
// shows in lakhs ("₹12.35 L", the exact amount on hover) or in full ("₹12,35,000.00"),
// chosen in the top bar and remembered in this browser, as the light or dark mode is. CSV
// exports are always exact; charts draw in lakhs either way.

import { createContext, useContext } from 'react'
import { formatExact, formatLakhs } from './format.ts'

export type AmountFormat = 'lakhs' | 'full'

const STORAGE_KEY = 'ledgerbridge.amounts'

/** The saved choice, else lakhs. */
export function initialAmountFormat(): AmountFormat {
  try {
    return window.localStorage.getItem(STORAGE_KEY) === 'full' ? 'full' : 'lakhs'
  } catch {
    return 'lakhs'
  }
}

export function saveAmountFormat(format: AmountFormat): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, format)
  } catch {
    // not kept: the choice still applies until the page is closed
  }
}

export interface AmountSetting {
  format: AmountFormat
  setFormat: (format: AmountFormat) => void
}

export const AmountFormatContext = createContext<AmountSetting>({ format: 'lakhs', setFormat: () => {} })

export function useAmountFormat(): AmountSetting {
  return useContext(AmountFormatContext)
}

/** An amount as the setting shows it. */
export function formatAmount(amount: string, format: AmountFormat): string {
  return format === 'full' ? formatExact(amount) : formatLakhs(amount)
}
