// The dashboard's apps (ADR-048; docs/design/dashboard.md Section 0.1, screen 1): a tile each
// on the apps home, each with its own top menu. Only apps and pages that work are listed, so
// the dashboard never offers something that isn't there yet.

export interface AppPage {
  key: string // the second part of the path: "#/<app>/<page>"
  label: string
}

export type AppIcon = 'reports'

export interface DashboardApp {
  key: string // the first part of the path: "#/<app>"
  title: string
  description: string
  icon: AppIcon
  pages: AppPage[] // the first is the app's start page
}

export const APPS: DashboardApp[] = [
  {
    key: 'reports',
    title: 'Reports',
    description: 'Profit and loss, balance sheet and sales, per company or combined.',
    icon: 'reports',
    pages: [
      { key: 'dashboard', label: 'Dashboard' },
      { key: 'profit-loss', label: 'Profit & Loss' },
    ],
  },
]

export function findApp(key: string | undefined): DashboardApp | undefined {
  return APPS.find((app) => app.key === key)
}
