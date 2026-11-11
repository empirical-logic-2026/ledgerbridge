// The loading delay (docs/design/dashboard.md Section 0.5): a placeholder shows only when a load
// takes longer than about 150 ms, so a quick load doesn't flicker.

import { useEffect, useState } from 'react'

/** How long a load may take before its placeholders show. */
export const SHOW_AFTER_MS = 150

/** True once `ms` have passed since the component appeared. */
export function useShownAfter(ms: number = SHOW_AFTER_MS): boolean {
  const [shown, setShown] = useState(ms <= 0)
  useEffect(() => {
    if (ms <= 0) return
    const timer = window.setTimeout(() => setShown(true), ms)
    return () => window.clearTimeout(timer)
  }, [ms])
  return shown
}
