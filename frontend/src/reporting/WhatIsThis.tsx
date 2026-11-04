// "What is this?" beside a report's title (docs/design/dashboard.md Section 0.4): what the page's
// figures mean, where they come from and how to compare them with the source, opened on click.
// It replaces the options side panel; every card and column also explains itself on hover.

import { Button, Popover } from 'antd'
import type { ReactNode } from 'react'

export function WhatIsThis({ children }: { children: ReactNode }) {
  return (
    <Popover content={<div className="what-is-this">{children}</div>} trigger="click" placement="bottomRight" title="What is this?">
      <Button size="small">What is this?</Button>
    </Popover>
  )
}
