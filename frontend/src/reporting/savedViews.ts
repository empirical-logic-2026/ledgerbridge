// Saved views of a report page (docs/design/dashboard.md Section 0.1, screen 6): a name and
// the page's URL query (companies, period, view, columns, filters), kept in this browser until
// login (M5) can keep them per user.

export interface SavedView {
  name: string
  query: string // "company=3&month=2026-04&view=month"
}

const key = (page: string) => `ledgerbridge.views.${page}`

export function loadViews(page: string): SavedView[] {
  try {
    const saved = JSON.parse(window.localStorage.getItem(key(page)) ?? '[]')
    return Array.isArray(saved) ? saved.filter((v) => typeof v?.name === 'string' && typeof v?.query === 'string') : []
  } catch {
    return []
  }
}

export function saveView(page: string, view: SavedView): SavedView[] {
  const views = [...loadViews(page).filter((v) => v.name !== view.name), view]
  window.localStorage.setItem(key(page), JSON.stringify(views))
  return views
}

export function deleteView(page: string, name: string): SavedView[] {
  const views = loadViews(page).filter((v) => v.name !== name)
  window.localStorage.setItem(key(page), JSON.stringify(views))
  return views
}
