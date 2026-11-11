// The dark top bar (docs/design/dashboard.md Section 0.4, ADR-050): the company logo and the
// product name, the module tabs (a module shows once it has a built page), and on the right the
// period toggles (MTD, QTD, YTD, FY, Custom: months or dates in a panel), the financial year,
// what to compare with (the previous period, last year or nothing: RPT-016, F-CMP-002), how
// amounts are shown (in lakhs or in full: F-FMT-001, F-FMT-002) and light or dark mode.

import { Button, Input, Popover, Select, Tooltip } from 'antd'
import { useState } from 'react'
import { useAmountFormat, type AmountFormat } from '../amountFormat.ts'
import type { FinancialYear } from '../api/types.ts'
import logo from '../assets/company-logo-wide.png'
import { formatDate, formatMonth, parseDisplayDate } from '../format.ts'
import { useShownAfter } from '../components/loading/delay.ts'
import { href, type Query } from '../router.ts'
import { COMPARE_OPTIONS, periodDates, TOGGLES, yearMonths, type Change, type CompareKind, type PeriodChoice, type Selection } from '../selection.ts'
import type { Mode } from '../theme.ts'
import { MoonIcon, SunIcon } from './icons.tsx'
import { builtNav, HOME } from './nav.ts'

interface Props {
  module: string | undefined // the module shown
  starting?: boolean // the app's first data (companies, periods) is loading: the logo pulses
  query: Query // the selection, kept on every link
  selection: Selection
  years: FinancialYear[]
  year: FinancialYear | undefined
  period: PeriodChoice | undefined
  onChange: Change
  mode: Mode
  onMode: (mode: Mode) => void
}

function DateInput({ label, value, onDate }: { label: string; value: string | undefined; onDate: (iso: string) => void }) {
  const [text, setText] = useState<string | null>(null)
  const shown = text ?? (value ? formatDate(value) : '')
  const valid = text === null || text === '' || parseDisplayDate(text) !== null
  const commit = () => {
    if (text === null) return
    const iso = parseDisplayDate(text)
    if (iso) onDate(iso)
    if (iso || text === '') setText(null)
  }
  return (
    <Input aria-label={label} className="date-input" placeholder="DD-MMM-YYYY" value={shown} status={valid ? undefined : 'error'}
      onChange={(e) => setText(e.target.value)} onBlur={commit} onPressEnter={commit} />
  )
}

/** Custom: month chips of the year (one or several, adjacent or not), or from/to dates. */
function CustomPanel({ year, period, onChange }: Pick<Props, 'year' | 'period' | 'onChange'>) {
  const months = year ? yearMonths(year) : []
  const chosen = new Set(period?.months ?? [])
  const [from, to] = period ? periodDates(period) : [undefined, undefined]
  const toggle = (m: string) => {
    const current = period?.months.length ? period.months : []
    const next = current.includes(m) ? current.filter((x) => x !== m) : [...current, m].sort()
    onChange({ toggle: 'custom', months: next, from: undefined, to: undefined })
  }
  return (
    <div className="picker-panel" aria-label="Custom period">
      <div className="picker-row picker-months">
        {months.map((m) => (
          <button key={m} type="button" className={chosen.has(m) ? 'chip chip-month active' : 'chip chip-month'} aria-pressed={chosen.has(m)} onClick={() => toggle(m)}>
            {formatMonth(`${m}-01`).slice(0, 3)}
          </button>
        ))}
      </div>
      <div className="picker-row">
        <span className="picker-label">Or dates</span>
        <DateInput label="From" value={from} onDate={(day) => onChange({ toggle: 'custom', from: day, to, months: [] })} />
        <DateInput label="To" value={to} onDate={(day) => onChange({ toggle: 'custom', to: day, from, months: [] })} />
      </div>
    </div>
  )
}

function PeriodToggles({ selection, years, year, period, onChange }: Pick<Props, 'selection' | 'years' | 'year' | 'period' | 'onChange'>) {
  return (
    <div className="top-period" role="group" aria-label="Period">
      {TOGGLES.map((t) => {
        const active = selection.toggle === t.key
        const button = (
          <button key={t.key} type="button" className={active ? 'toggle active' : 'toggle'} aria-pressed={active} title={t.title}
            onClick={() => t.key !== 'custom' && onChange({ toggle: t.key, months: [], from: undefined, to: undefined })}>
            {t.label}
            {t.key === 'custom' && ' ▾'}
          </button>
        )
        return t.key === 'custom' ? (
          <Popover key={t.key} trigger="click" placement="bottomRight" content={<CustomPanel year={year} period={period} onChange={onChange} />}>
            {button}
          </Popover>
        ) : (
          button
        )
      })}
      <Select aria-label="Financial year" size="small" className="top-select" value={year?.start_year} popupMatchSelectWidth={false}
        options={years.map((y) => ({ value: y.start_year, label: y.label }))}
        onChange={(fy: number) => onChange({ fy, toggle: selection.toggle === 'custom' ? 'fy' : selection.toggle, months: [], from: undefined, to: undefined })} />
      <Select aria-label="Compare" size="small" className="top-select" value={selection.compare} popupMatchSelectWidth={false}
        options={COMPARE_OPTIONS} onChange={(compare: CompareKind) => onChange({ compare })} />
    </div>
  )
}

const AMOUNT_OPTIONS: { value: AmountFormat; label: string }[] = [
  { value: 'lakhs', label: 'Amounts in lakhs' },
  { value: 'full', label: 'Full amounts' },
]

/** Lakhs ("₹12.35 L", the exact amount on hover) or full amounts, everywhere. */
function AmountsSelect() {
  const { format, setFormat } = useAmountFormat()
  return (
    <Select aria-label="Amounts" size="small" className="top-select" value={format} popupMatchSelectWidth={false}
      options={AMOUNT_OPTIONS} onChange={setFormat} />
  )
}

/** The company logo; it pulses gently while the app's first data loads (after 150 ms, as every
 *  placeholder: components/loading/Loading.tsx). */
function Logo({ starting }: { starting: boolean }) {
  return starting ? <StartingLogo /> : <LogoImage className="top-logo" />
}

function StartingLogo() {
  const shown = useShownAfter()
  return <LogoImage className={shown ? 'top-logo logo-pulse' : 'top-logo'} busy />
}

function LogoImage({ className, busy }: { className: string; busy?: boolean }) {
  return (
    <span className={className} aria-busy={busy || undefined} data-testid="top-logo">
      <img src={logo} alt="Empirical Logic" />
    </span>
  )
}

export function TopBar(props: Props) {
  const modules = builtNav()
  return (
    <header className="top-bar">
      <a href={href([...HOME], props.query)} className="top-brand" aria-label="LedgerBridge: Overview">
        <Logo starting={props.starting ?? false} />
        <span className="top-name">LedgerBridge</span>
      </a>
      <nav className="top-modules" aria-label="Modules">
        {modules.map((m) => {
          const active = props.module === m.key
          return (
            <a key={m.key} href={href([m.key, m.pages[0].key], props.query)} className={active ? 'top-module active' : 'top-module'} aria-current={active ? 'page' : undefined}>
              {m.label}
            </a>
          )
        })}
      </nav>
      <div className="top-right">
        {props.years.length > 0 && (
          <PeriodToggles selection={props.selection} years={props.years} year={props.year} period={props.period} onChange={props.onChange} />
        )}
        <AmountsSelect />
        <Tooltip title={props.mode === 'dark' ? 'Light mode' : 'Dark mode'}>
          <Button type="text" className="on-dark" aria-label={props.mode === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
            icon={props.mode === 'dark' ? <SunIcon /> : <MoonIcon />} onClick={() => props.onMode(props.mode === 'dark' ? 'light' : 'dark')} />
        </Tooltip>
      </div>
    </header>
  )
}
