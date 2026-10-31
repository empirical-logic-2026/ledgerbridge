// A small router of our own (ADR-048: no new dependency): the page is the part of the URL
// after "#", e.g. "#/overview?company=3&fy=2026&as_of=2026-09-30". Hash routes need no
// server set-up, survive a reload and can be bookmarked; the query keeps the selection.

import { useSyncExternalStore } from 'react'

export interface Route {
  path: string[] // "#/statements/profit-loss" -> ["statements", "profit-loss"]
  query: URLSearchParams
}

export function parseHash(hash: string): Route {
  const text = hash.replace(/^#/, '')
  const [path = '', search = ''] = text.split('?', 2)
  return {
    path: path.split('/').filter(Boolean).map(decodeURIComponent),
    query: new URLSearchParams(search),
  }
}

type Value = string | number | null | undefined
export type Query = Record<string, Value | Value[]>

/** "#/a/b?x=1&m=2&m=3": the href for a path and query (lists repeat their key; empty values
 *  are left out). */
export function href(path: string[], query: Query = {}): string {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    for (const item of Array.isArray(value) ? value : [value]) {
      if (item !== null && item !== undefined && item !== '') params.append(key, String(item))
    }
  }
  const search = params.toString()
  return `#/${path.map(encodeURIComponent).join('/')}${search ? `?${search}` : ''}`
}

export function navigate(path: string[], query: Query = {}): void {
  window.location.hash = href(path, query)
}

/** The query as plain values (repeated keys as lists). */
export function queryValues(query: URLSearchParams): Query {
  const values: Query = {}
  for (const key of new Set(query.keys())) {
    const all = query.getAll(key)
    values[key] = all.length > 1 ? all : all[0]
  }
  return values
}

/** Goes to the same page with some query keys changed (undefined removes one); the other
 *  keys stay, so the selection and a page's own options don't overwrite each other. */
export function updateQuery(route: Route, change: Query): void {
  navigate(route.path, { ...queryValues(route.query), ...change })
}

function subscribe(onChange: () => void): () => void {
  window.addEventListener('hashchange', onChange)
  return () => window.removeEventListener('hashchange', onChange)
}

/** The current route; the component renders again when it changes. */
export function useRoute(): Route {
  const hash = useSyncExternalStore(subscribe, () => window.location.hash)
  return parseHash(hash)
}
