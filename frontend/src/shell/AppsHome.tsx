// The apps home: one tile per app (ADR-048), with the search bar to find one.

import { Card, Flex, Typography } from 'antd'
import { useState } from 'react'
import { href, type Query } from '../router.ts'
import { APPS } from './apps.ts'
import { EMPTY_SEARCH } from './search.ts'
import { SearchBar } from './SearchBar.tsx'

export function AppsHome({ query = {} }: { query?: Query }) {
  const [search, setSearch] = useState(EMPTY_SEARCH)
  const text = search.text.trim().toLowerCase()
  const shown = APPS.filter((app) => `${app.title} ${app.description}`.toLowerCase().includes(text))
  return (
    <Flex vertical gap={16}>
      <Typography.Title level={3} style={{ margin: 0 }}>
        Apps
      </Typography.Title>
      <SearchBar value={search} onChange={setSearch} favouritesKey="apps" placeholder="Find an app…" />
      <div className="tiles">
        {shown.map((app) => (
          <a key={app.key} href={href([app.key], query)} className="tile-link">
            <Card hoverable className="tile">
              <Typography.Title level={4} style={{ marginTop: 0 }}>
                {app.title}
              </Typography.Title>
              <Typography.Text type="secondary">{app.description}</Typography.Text>
            </Card>
          </a>
        ))}
        {shown.length === 0 && <Typography.Text type="secondary">No app matches.</Typography.Text>}
      </div>
    </Flex>
  )
}
