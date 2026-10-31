// Our colours, defined once (docs/design/dashboard.md Section 5): charcoal black for the top
// bar, side panels and dark surfaces; forest green for primary actions, links, selections and
// positive figures; crimson for negative figures, losses, alerts and warnings, used sparingly
// so that red keeps its meaning. Every text colour meets WCAG AA (4.5:1) on the surface it is
// used on (measured: src/theme.test.ts). Root writes the tokens as CSS variables (--lb-*)
// for the stylesheet; Ant Design and the charts read them from here.

import { theme, type ThemeConfig } from 'antd'

export type Mode = 'light' | 'dark'

export interface Tokens {
  charcoal: string // top bar, side panels
  onCharcoal: string // text on charcoal
  onCharcoalMuted: string
  page: string
  surface: string
  border: string
  text: string
  muted: string
  primary: string // buttons and selected things (white text on it)
  positive: string // green text: links, positive figures and changes
  primarySoft: string // selected chips, highlights
  primaryLine: string // borders of selected things
  negative: string // crimson text: negative figures, losses, alerts
  negativeSoft: string
  neutralBar: string // the second series in charts (purchases)
}

const CHARCOAL = '#1C1F23'
const FOREST = '#1E6B3A'

export const tokens: Record<Mode, Tokens> = {
  light: {
    charcoal: CHARCOAL,
    onCharcoal: '#FFFFFF',
    onCharcoalMuted: '#C4C9CF',
    page: '#F4F5F6',
    surface: '#FFFFFF',
    border: '#E3E5E8',
    text: '#16181B',
    muted: '#5F6368',
    primary: FOREST,
    positive: FOREST,
    primarySoft: '#DCEFE2',
    primaryLine: '#7FC49A',
    negative: '#B0102D',
    negativeSoft: '#FBE7EA',
    neutralBar: '#9AA1A9',
  },
  dark: {
    charcoal: CHARCOAL,
    onCharcoal: '#FFFFFF',
    onCharcoalMuted: '#C4C9CF',
    page: '#141619',
    surface: '#202327',
    border: '#33373D',
    text: '#E6E8EA',
    muted: '#9AA1A9',
    primary: FOREST,
    positive: '#6FCF97',
    primarySoft: '#1F3A2A',
    primaryLine: '#3F8F5F',
    negative: '#FF7A8A',
    negativeSoft: '#3A1D22',
    neutralBar: '#6B727A',
  },
}

/** The tokens as CSS variables: `--lb-primary-soft` and so on. */
export function cssVariables(mode: Mode): Record<string, string> {
  return Object.fromEntries(
    Object.entries(tokens[mode]).map(([key, value]) => [`--lb-${key.replace(/[A-Z]/g, (c) => `-${c.toLowerCase()}`)}`, value]),
  )
}

export function themeConfig(mode: Mode): ThemeConfig {
  const t = tokens[mode]
  return {
    algorithm: mode === 'dark' ? theme.darkAlgorithm : theme.defaultAlgorithm,
    token: {
      colorPrimary: t.primary,
      colorLink: t.positive,
      colorSuccess: t.positive,
      colorError: t.negative,
      colorWarning: t.negative, // no amber: warnings are crimson, used sparingly
      colorText: t.text,
      colorTextSecondary: t.muted,
      colorBgLayout: t.page,
      colorBgContainer: t.surface,
      colorBorder: t.border,
      borderRadius: 8,
      fontFamily: "'IBM Plex Sans', 'Segoe UI', system-ui, sans-serif",
    },
    components: {
      Layout: { headerBg: t.charcoal, headerHeight: 56, headerPadding: '0 16px' },
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
