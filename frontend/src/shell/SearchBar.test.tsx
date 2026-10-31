import { fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'
import { beforeEach, describe, expect, it } from 'vitest'
import { EMPTY_SEARCH, type SearchState } from './search.ts'
import { SearchBar } from './SearchBar.tsx'

let last: SearchState = EMPTY_SEARCH

function Harness() {
  const [search, setSearch] = useState(EMPTY_SEARCH)
  return (
    <SearchBar
      value={search}
      onChange={(next) => {
        last = next
        setSearch(next)
      }}
      favouritesKey="test"
      filters={[{ key: 'voucher_type', label: 'Voucher type', choices: [{ value: '5', label: 'Sales' }] }]}
      groupBys={[
        { key: 'month', label: 'Month' },
        { key: 'ledger', label: 'Ledger' },
      ]}
    />
  )
}

function openPanel() {
  fireEvent.click(screen.getByRole('button', { name: 'Filters, group by and favourites' }))
}

describe('the search bar', () => {
  beforeEach(() => {
    window.localStorage.clear()
    last = EMPTY_SEARCH
  })

  it('adds filters and group-bys as removable facets', async () => {
    render(<Harness />)
    openPanel()
    fireEvent.click(await screen.findByText('Sales'))
    fireEvent.click(screen.getByText('Month'))
    fireEvent.click(screen.getByText('Ledger'))
    expect(last.filters).toEqual([{ key: 'voucher_type', value: '5', label: 'Voucher type: Sales' }])
    expect(last.groupBy).toEqual(['month', 'ledger'])
    expect(screen.getByText('Group by: Month › Ledger')).toBeInTheDocument()
    expect(screen.getByText('Voucher type: Sales')).toBeInTheDocument()
  })

  it('saves favourites in this browser and applies them', async () => {
    render(<Harness />)
    fireEvent.change(screen.getByLabelText('Search'), { target: { value: 'rent' } })
    openPanel()
    fireEvent.change(await screen.findByLabelText('Favourite name'), { target: { value: 'Rent' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    const saved = JSON.parse(window.localStorage.getItem('ledgerbridge.favourites.test') ?? '[]')
    expect(saved).toEqual([{ name: 'Rent', search: { text: 'rent', filters: [], groupBy: [] } }])
    fireEvent.change(screen.getByLabelText('Search'), { target: { value: '' } })
    fireEvent.click(screen.getByRole('button', { name: 'Rent' }))
    expect(last.text).toBe('rent')
  })

  it('ignores saved favourites it cannot read', async () => {
    window.localStorage.setItem('ledgerbridge.favourites.test', '{"broken": true')
    render(<Harness />)
    openPanel()
    expect(await screen.findByText('None saved yet')).toBeInTheDocument()
  })
})
