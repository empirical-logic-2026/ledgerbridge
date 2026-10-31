// The sync status line: whether the source had the companies loaded when last checked, the
// last sync, and whether every latest validation passed.

import type { Company } from '../api/types.ts'
import { timeAgo } from '../format.ts'

export function syncStatus(companies: Company[]): { text: string; ok: boolean } | null {
  if (!companies.length) return null
  const source = companies[0].health.source_name ?? 'Source'
  const loaded = companies.filter((c) => c.health.source_loaded).length
  const synced = companies.map((c) => c.health.last_sync_at).filter((d): d is string => !!d).sort().pop()
  const statuses = companies.map((c) => c.health.validation_status)
  const passed = statuses.every((s) => s === 'passed')
  const checks = passed ? 'all checks passed' : statuses.some((s) => s === 'failed') ? 'checks failed' : 'not all checked'
  return {
    text: `${source}: ${loaded} of ${companies.length} loaded · ${synced ? `synced ${timeAgo(synced)}` : 'never synced'} · ${checks}`,
    ok: passed && loaded === companies.length,
  }
}
