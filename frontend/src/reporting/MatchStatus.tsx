// Whether a report's figures match the source's own statements for the companies and dates
// used (formulas F-CHK-001 to F-CHK-003), shown under the report's title.

import type { MatchingOut } from '../api/types.ts'
import { formatDate } from '../format.ts'

export function MatchStatus({ matching, companiesLabel, sourceName }: { matching: MatchingOut | undefined; companiesLabel: string; sourceName: string }) {
  if (!matching) return null
  const last = matching.dates.length ? formatDate(matching.dates[matching.dates.length - 1]) : null
  if (matching.matches) {
    return (
      <p className="match match-ok" role="status">
        ✓ Matches {sourceName} for {companiesLabel}
        {last ? ` (checked at ${matching.dates.length} statement dates up to ${last})` : ''}
      </p>
    )
  }
  if (matching.differing > 0) {
    return (
      <p className="match match-bad" role="status">
        ✗ {matching.differing} line{matching.differing === 1 ? '' : 's'} differ from {sourceName} at the dates used. See Data checks, or run{' '}
        <code>./dev.ps1 statements</code>.
      </p>
    )
  }
  return (
    <p className="match match-unknown" role="status">
      Not yet compared with {sourceName} for {matching.unchecked} of the companies and dates used: run{' '}
      <code>./dev.ps1 statements</code>.
    </p>
  )
}
