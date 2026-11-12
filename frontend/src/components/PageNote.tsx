// A short explanation at the top of every page (docs/design/dashboard.md Section 0.5): a small
// box the reader can close, open the first time and then as they last left it on that page
// (kept in this browser only, one key per page). A native <details>: its title is a button for
// the keyboard (Enter or Space), and screen readers announce it as expandable. Each page's text
// lives in its module's notes.ts, next to the page's labels; shell/pageNotes.ts says which note
// a page shows, and App.tsx puts it at the top.

import { useState } from 'react'

export interface NoteContent {
  title: string // "About this page"
  points: { label?: string; text: string }[] // 3 to 6 short points; a label in bold first
  footer?: string // which Tally report to compare it with
}

const PREFIX = 'ledgerbridge.note.'

/** Whether the note starts open: open unless the reader closed it on this page. */
function noteIsOpen(key: string): boolean {
  try {
    return window.localStorage.getItem(key) !== 'closed'
  } catch {
    return true // storage blocked: open
  }
}

function remember(key: string, open: boolean): void {
  try {
    if (open) window.localStorage.removeItem(key)
    else window.localStorage.setItem(key, 'closed')
  } catch {
    // storage blocked: the note opens again next time
  }
}

/** `page` names the page ("sales-dashboard"): the note's own key in this browser. */
export function PageNote({ page, note, pageTitle }: { page: string; note: NoteContent; pageTitle: string }) {
  const key = `${PREFIX}${page}`
  const [open] = useState(() => noteIsOpen(key))
  return (
    <details className="card page-note" open={open} onToggle={(e) => remember(key, e.currentTarget.open)} data-note={page}
      aria-label={`About this page: ${pageTitle}`}>
      <summary className="page-note-title">{note.title}</summary>
      <ul className="page-note-points">
        {note.points.map((p) => (
          <li key={p.label ?? p.text}>
            {p.label && <strong>{p.label}:</strong>} {p.text}
          </li>
        ))}
      </ul>
      {note.footer && <p className="page-note-footer">{note.footer}</p>}
    </details>
  )
}
