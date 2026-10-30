// How the dashboard calls the data plane's API. The browser calls it directly on this
// computer (VITE_API_BASE_URL, set by `./dev.ps1 dashboard`); the API allows only this
// dashboard's origin, GET only (ADR-049). Response types are generated: ./types.ts.

import type { Query } from '../router.ts'

export const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8001'

export interface Health {
  status: 'ok'
  env: string
  version: string
}

/** The API's own message for a refused request ("Unknown parameter 'x'."), else a status. */
export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

/** `?company=3&company=4`: arrays become repeated parameters, empty values are left out. */
export function queryString(query: Query | Record<string, unknown> = {}): string {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    for (const item of Array.isArray(value) ? value : [value]) {
      if (item !== null && item !== undefined && item !== '') params.append(key, String(item))
    }
  }
  const text = params.toString()
  return text ? `?${text}` : ''
}

export async function getJson<T>(path: string, query: Record<string, unknown> = {}): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}${queryString(query)}`)
  if (!response.ok) {
    let message = `Request failed (${response.status})`
    try {
      const body = (await response.json()) as { detail?: unknown }
      if (typeof body.detail === 'string') message = body.detail
    } catch {
      // not JSON: keep the status
    }
    throw new ApiError(response.status, message)
  }
  return (await response.json()) as T
}
