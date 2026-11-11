// A label with its explanation on hover (help/glossary.ts): what the value or status means and
// how it is worked out, with its formula and its ID in docs/formula-sheet.md. Underlined with dots
// when there is one; plain text when there isn't.

import { Tooltip } from 'antd'
import type { ReactNode } from 'react'
import { explain } from '../help/glossary.ts'

export function Explained({ label, help, children }: { label: string; help?: string; children?: ReactNode }) {
  const text = help ?? explain(label)
  const shown = children ?? label
  if (!text) return <>{shown}</>
  return (
    <Tooltip title={text} mouseEnterDelay={0.2}>
      <span className="has-help">{shown}</span>
    </Tooltip>
  )
}
