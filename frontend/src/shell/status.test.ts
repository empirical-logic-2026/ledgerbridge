import { describe, expect, it } from 'vitest'
import type { Company, DataHealth } from '../api/types.ts'
import { syncStatus } from './status.ts'

function company(health: Partial<DataHealth>): Company {
  return {
    id: 1,
    code: 'TEST',
    name: 'Test Co',
    display_name: 'Test Co',
    books_from: '2026-04-01',
    fy_start_month: 4,
    health: {
      last_sync_at: '2026-11-04T10:00:00',
      validation_status: 'passed',
      validated_as_of: '2026-10-31',
      validated_at: '2026-11-04T10:00:00',
      source_name: 'Test source',
      source_loaded: true,
      source_checked_at: '2026-11-04T10:00:00',
      source_checked_by: 'sync',
      ...health,
    },
  }
}

describe('synchronization status', () => {
  it('distinguishes all-loaded, failed-check, incomplete-check, and not-loaded states', () => {
    expect(syncStatus([company({})])).toMatchObject({ ok: true, text: /all checks passed/ })
    expect(syncStatus([company({ validation_status: 'failed' })])).toMatchObject({
      ok: false,
      text: /checks failed/,
    })
    expect(syncStatus([company({ validation_status: 'running' })])).toMatchObject({
      ok: false,
      text: /not all checked/,
    })
    expect(syncStatus([company({ source_loaded: false })])).toMatchObject({
      ok: false,
      text: /0 of 1 loaded/,
    })
    expect(syncStatus([])).toBeNull()
  })
})