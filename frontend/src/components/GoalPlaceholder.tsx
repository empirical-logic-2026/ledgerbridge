// Where a goal tracker will go (docs/design/dashboard.md Section 0.4): goals need targets, and
// targets come with budgets (milestone M7b), so until then the card says so.

export function GoalPlaceholder({ goals }: { goals: string[] }) {
  return (
    <section className="card goal-placeholder" aria-label="Goal tracker">
      <h2 className="card-title">Goal tracker</h2>
      <p className="card-note">
        Progress towards targets ({goals.join(', ')}) needs the targets themselves. They come with budgets (milestone M7b); until then there is
        nothing to track against.
      </p>
    </section>
  )
}
