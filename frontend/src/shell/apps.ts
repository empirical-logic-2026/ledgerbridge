// The dashboard's apps (ADR-048): one tile each on the apps home, each with its own menu.
// D1 part b has Overview; Statements and Explore arrive with part c. Only apps that work
// are listed, so the dashboard never offers something that isn't there yet.

export interface AppMenuItem {
  key: string // the second part of the path: "#/overview/<key>"
  label: string
}

export interface DashboardApp {
  key: string // the first part of the path: "#/<key>"
  title: string
  description: string
  menu: AppMenuItem[]
}

export const APPS: DashboardApp[] = [
  {
    key: 'overview',
    title: 'Overview',
    description: 'Sales, profit, cash and what is owed, for one company or all of them.',
    menu: [{ key: 'summary', label: 'Summary' }],
  },
]

export function findApp(key: string | undefined): DashboardApp | undefined {
  return APPS.find((app) => app.key === key)
}
