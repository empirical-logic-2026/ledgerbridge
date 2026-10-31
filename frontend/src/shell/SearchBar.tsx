// The search bar every list gets (ADR-048): free text, filter facets and group-by facets
// shown as removable tags, a panel to add them, and favourites (saved searches) kept in
// this browser until login (M5) can keep them per user. What the facets mean is up to the
// list using it; the bar only edits the search.

import { Button, Flex, Input, Popover, Tag, Typography } from 'antd'
import { useState } from 'react'
import type { FilterChoice, FilterOption, GroupOption, SearchState } from './search.ts'

interface Favourite {
  name: string
  search: SearchState
}

interface Props {
  value: SearchState
  onChange: (next: SearchState) => void
  filters?: FilterOption[]
  groupBys?: GroupOption[]
  favouritesKey: string // where this list's favourites are kept
  placeholder?: string
}

function loadFavourites(key: string): Favourite[] {
  try {
    const saved = JSON.parse(window.localStorage.getItem(`ledgerbridge.favourites.${key}`) ?? '[]')
    return Array.isArray(saved) ? (saved as Favourite[]) : []
  } catch {
    return []
  }
}

function saveFavourites(key: string, favourites: Favourite[]): void {
  window.localStorage.setItem(`ledgerbridge.favourites.${key}`, JSON.stringify(favourites))
}

export function SearchBar({ value, onChange, filters = [], groupBys = [], favouritesKey, placeholder = 'Search…' }: Props) {
  const [favourites, setFavourites] = useState(() => loadFavourites(favouritesKey))
  const [name, setName] = useState('')
  const labelOf = (key: string) => groupBys.find((g) => g.key === key)?.label ?? key

  const toggleFilter = (option: FilterOption, choice: FilterChoice) => {
    const active = value.filters.some((f) => f.key === option.key && f.value === choice.value)
    onChange({
      ...value,
      filters: active
        ? value.filters.filter((f) => !(f.key === option.key && f.value === choice.value))
        : [...value.filters, { key: option.key, value: choice.value, label: `${option.label}: ${choice.label}` }],
    })
  }
  const toggleGroup = (key: string) => {
    const groupBy = value.groupBy.includes(key) ? value.groupBy.filter((k) => k !== key) : [...value.groupBy, key]
    onChange({ ...value, groupBy })
  }
  const saveCurrent = () => {
    const trimmed = name.trim()
    if (!trimmed) return
    const next = [...favourites.filter((f) => f.name !== trimmed), { name: trimmed, search: value }]
    saveFavourites(favouritesKey, next)
    setFavourites(next)
    setName('')
  }
  const remove = (favourite: Favourite) => {
    const next = favourites.filter((f) => f.name !== favourite.name)
    saveFavourites(favouritesKey, next)
    setFavourites(next)
  }

  const panel = (
    <Flex gap={32} wrap className="search-panel">
      {filters.length > 0 && (
        <div>
          <Typography.Text strong>Filters</Typography.Text>
          {filters.map((option) => (
            <div key={option.key} className="search-panel-group">
              <Typography.Text type="secondary">{option.label}</Typography.Text>
              {option.choices.map((choice) => (
                <Tag.CheckableTag
                  key={choice.value}
                  checked={value.filters.some((f) => f.key === option.key && f.value === choice.value)}
                  onChange={() => toggleFilter(option, choice)}
                >
                  {choice.label}
                </Tag.CheckableTag>
              ))}
            </div>
          ))}
        </div>
      )}
      {groupBys.length > 0 && (
        <div>
          <Typography.Text strong>Group by</Typography.Text>
          <Flex vertical gap={4} className="search-panel-group">
            {groupBys.map((g) => (
              <Tag.CheckableTag key={g.key} checked={value.groupBy.includes(g.key)} onChange={() => toggleGroup(g.key)}>
                {g.label}
              </Tag.CheckableTag>
            ))}
          </Flex>
        </div>
      )}
      <div>
        <Typography.Text strong>Favourites</Typography.Text>
        <Flex vertical gap={4} className="search-panel-group">
          {favourites.length === 0 && <Typography.Text type="secondary">None saved yet</Typography.Text>}
          {favourites.map((f) => (
            <Flex key={f.name} gap={8} align="center">
              <Button type="link" size="small" onClick={() => onChange(f.search)}>
                {f.name}
              </Button>
              <Button type="text" size="small" aria-label={`Delete favourite ${f.name}`} onClick={() => remove(f)}>
                ×
              </Button>
            </Flex>
          ))}
          <Flex gap={4}>
            <Input
              size="small"
              aria-label="Favourite name"
              placeholder="Name this search"
              value={name}
              onChange={(e) => setName(e.target.value)}
              onPressEnter={saveCurrent}
            />
            <Button size="small" onClick={saveCurrent}>
              Save
            </Button>
          </Flex>
        </Flex>
      </div>
    </Flex>
  )

  return (
    <Flex className="search-bar" align="center" gap={6} wrap>
      {value.groupBy.length > 0 && (
        <Tag color="blue" closable onClose={() => onChange({ ...value, groupBy: [] })}>
          Group by: {value.groupBy.map(labelOf).join(' › ')}
        </Tag>
      )}
      {value.filters.map((f) => (
        <Tag
          key={`${f.key}=${f.value}`}
          closable
          onClose={() => onChange({ ...value, filters: value.filters.filter((x) => x !== f) })}
        >
          {f.label}
        </Tag>
      ))}
      <Input
        variant="borderless"
        aria-label="Search"
        placeholder={placeholder}
        value={value.text}
        onChange={(e) => onChange({ ...value, text: e.target.value })}
        style={{ flex: 1, minWidth: 160 }}
      />
      <Popover content={panel} trigger="click" placement="bottomRight">
        <Button aria-label="Filters, group by and favourites">Filters ▾</Button>
      </Popover>
    </Flex>
  )
}
