// Our visual identity as Ant Design theme tokens (docs/design/dashboard.md Section 5;
// ADR-048: our own colours, nothing taken from Odoo). Light and dark use the same accents.

import { theme, type ThemeConfig } from 'antd'

export type Mode = 'light' | 'dark'

export const palette = {
  primary: '#0F766E', // dark teal: primary actions, sales bars, active items
  primarySoft: '#CCFBF1',
  topBar: '#1F2937', // dark navy
  good: '#15803D',
  watch: '#B45309',
  bad: '#B91C1C',
}

export function themeConfig(mode: Mode): ThemeConfig {
  return {
    algorithm: mode === 'dark' ? theme.darkAlgorithm : theme.defaultAlgorithm,
    token: {
      colorPrimary: palette.primary,
      colorSuccess: palette.good,
      colorWarning: palette.watch,
      colorError: palette.bad,
      borderRadius: 8,
      colorBgLayout: mode === 'dark' ? '#0B1220' : '#F5F6F8',
    },
    components: {
      Layout: { headerBg: palette.topBar, headerHeight: 56, headerPadding: '0 16px' },
    },
  }
}

const STORAGE_KEY = 'ledgerbridge.mode'

/** The saved mode, else the system's preference. */
export function initialMode(): Mode {
  const saved = window.localStorage.getItem(STORAGE_KEY)
  if (saved === 'light' || saved === 'dark') return saved
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export function saveMode(mode: Mode): void {
  window.localStorage.setItem(STORAGE_KEY, mode)
}
