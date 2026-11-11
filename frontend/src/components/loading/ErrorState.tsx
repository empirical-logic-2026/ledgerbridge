// A request that failed (docs/design/dashboard.md Section 0.5): what couldn't be loaded, the
// reason the API gave, and a Retry button that asks again (the query's refetch). While the
// retry runs the button shows it is busy; a new failure shows the new reason.

import { Button } from 'antd'
import { useState } from 'react'

interface Props {
  message: string // "The Balance Sheet couldn't be loaded."
  error: Error
  onRetry?: () => void // none: no Retry button (nothing to ask again)
}

export function ErrorState({ message, error, onRetry }: Props) {
  // The error that Retry was pressed for: busy until that error is replaced (by data or a new error).
  const [retriedFor, setRetriedFor] = useState<Error | null>(null)
  const retrying = retriedFor === error
  const retry = () => {
    setRetriedFor(error)
    onRetry?.()
  }
  return (
    <section className="card error-state" role="alert">
      <div className="error-state-text">
        <h2 className="error-state-title">{message}</h2>
        <p className="error-state-reason">{error.message}</p>
      </div>
      {onRetry && (
        <Button type="primary" onClick={retry} loading={retrying}>
          Retry
        </Button>
      )}
    </section>
  )
}
