// A short explanation at the top of a page (docs/design/dashboard.md Section 0.5): a small box
// the reader can close, open the first time and then as they last left it on that page (kept
// in this browser only). A native <details>: its title is a button for the keyboard, and screen
// readers announce it as expandable. The text lives next to each page's labels.

import { useState } from 'react'

export interface NoteContent {
  title: string // "How ageing is worked out"
  points: { label?: string; text: string }[] // 3 to 6 short points; a label in bold first
  footer?: string
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

/** `page` names the page ("parties-receivables"); `storageKey` keeps an older note's key. */
export function PageNote({ page, note, storageKey }: { page: string; note: NoteContent; storageKey?: string }) {
  const key = storageKey ?? `${PREFIX}${page}`
  const [open] = useState(() => noteIsOpen(key))
  return (
    <details className="card page-note" open={open} onToggle={(e) => remember(key, e.currentTarget.open)} data-note={page}>
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
