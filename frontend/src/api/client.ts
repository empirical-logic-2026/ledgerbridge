// Shared API types will be generated from the backend OpenAPI schema once
// real endpoints exist (M6/M7). Until then the few M0 types live here.

export const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

export interface Health {
  status: 'ok'
  env: string
  version: string
}

export async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`)
  if (!response.ok) {
    throw new Error(`Request to ${path} failed with status ${response.status}`)
  }
  return (await response.json()) as T
}
