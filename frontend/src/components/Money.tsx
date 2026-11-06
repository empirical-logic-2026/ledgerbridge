// An amount as the Amounts setting shows it (amountFormat.ts): in lakhs with the exact amount
// on hover, or in full. Negative amounts in the negative colour. And the provider that keeps
// the setting for the whole dashboard.

import { Tooltip } from 'antd'
import { useState, type ReactNode } from 'react'
import { AmountFormatContext, formatAmount, initialAmountFormat, saveAmountFormat, useAmountFormat, type AmountFormat } from '../amountFormat.ts'
import { formatExact, toScaled } from '../format.ts'

export function Money({ value, className }: { value: string | null | undefined; className?: string }) {
  const { format } = useAmountFormat()
  if (value === null || value === undefined) return <span>—</span>
  const css = [className, toScaled(value) < 0n ? 'negative' : undefined].filter(Boolean).join(' ') || undefined
  const text = <span className={css}>{formatAmount(value, format)}</span>
  return format === 'full' ? text : <Tooltip title={formatExact(value)}>{text}</Tooltip>
}

export function AmountFormatProvider({ children }: { children: ReactNode }) {
  const [format, setState] = useState<AmountFormat>(initialAmountFormat)
  const setFormat = (next: AmountFormat) => {
    saveAmountFormat(next)
    setState(next)
  }
  return <AmountFormatContext.Provider value={{ format, setFormat }}>{children}</AmountFormatContext.Provider>
}
