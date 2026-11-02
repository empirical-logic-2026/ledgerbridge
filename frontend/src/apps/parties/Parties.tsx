// The Customers and Vendors lists (docs/design/dashboard.md Section 0.3): each party by name
// across the selected companies, with its sales (purchases) in the period, invoices, the last
// one and the balance due at the period's end; a name opens the party's page. Figures:
// core/parties.py (GET /api/v1/parties/{kind}).

import { Alert, Skeleton } from 'antd'
import type { Company, PartiesOut, PartyRowOut } from '../../api/types.ts'
import type { ExplorerColumn } from '../../reporting/explorer.ts'
import { ExplorerTable } from '../../reporting/ExplorerTable.tsx'
import { ReportFrame, type PanelProps } from '../../reporting/ReportFrame.tsx'
import type { Query } from '../../router.ts'
import { href } from '../../router.ts'
import { PARTY_WORDS, type PartyKind } from './words.ts'

interface Props extends PanelProps {
  kind: PartyKind
  companies: Company[]
  parties: PartiesOut | undefined
  loading: boolean
  error: Error | null
}

function columns(kind: PartyKind, names: Map<number, string>, combined: boolean, query: Query): ExplorerColumn<PartyRowOut>[] {
  const w = PARTY_WORDS[kind]
  return [
    { key: 'name', label: w.one, kind: 'text', value: (p) => p.name, link: (p) => href([...w.group, String(p.party_id)], query) },
    { key: 'net', label: w.net, kind: 'amount', value: (p) => p.net },
    { key: 'invoices', label: 'Invoices', kind: 'count', value: (p) => p.invoices },
    { key: 'last', label: 'Last invoice', kind: 'date', value: (p) => p.last_invoice },
    { key: 'balance', label: w.balance, kind: 'amount', value: (p) => p.balance },
    { key: 'companies', label: 'Companies', kind: 'text', value: (p) => p.companies.map((c) => names.get(c) ?? `Company ${c}`).join(', '), groupable: true, hidden: !combined },
  ]
}

function help(kind: PartyKind) {
  const w = PARTY_WORDS[kind]
  return function Help(sourceName: string) {
    return (
      <>
        <p>
          Every {w.one.toLowerCase()} of the companies you chose, by name: the same {w.one.toLowerCase()} in several companies is one row, their
          figures added together. <strong>{w.net}</strong> and invoices are for the period; the <strong>{w.balance.toLowerCase()}</strong> is at its
          end (the ledgers' openings and every entry up to that day).
        </p>
        <p>
          <strong>To compare with {sourceName}:</strong> the balances are those of the {w.debtors} group summary on the same date; the{' '}
          {w.net.toLowerCase()} the {kind === 'customers' ? 'Sales' : 'Purchase'} Register for the party.
        </p>
      </>
    )
  }
}

export function Parties(props: Props) {
  const { kind, parties } = props
  const names = new Map(props.companies.map((c) => [c.id, c.name]))
  let content: React.ReactNode
  if (props.error) {
    content = <Alert type="error" showIcon message={`The ${PARTY_WORDS[kind].title.toLowerCase()} couldn't be loaded.`} description={props.error.message} />
  } else if (props.loading || !parties) {
    content = <Skeleton active paragraph={{ rows: 10 }} />
  } else {
    content = (
      <ExplorerTable
        id={`${kind}-list`}
        label={PARTY_WORDS[kind].title}
        columns={columns(kind, names, parties.combined, props.query)}
        rows={parties.parties}
        rowKey={(p) => String(p.party_id)}
        sortKey="net"
        descending
        totalLabel="Total"
      />
    )
  }
  return (
    <ReportFrame {...props} title={PARTY_WORDS[kind].title} page={`${kind}-list`} period={parties?.period} combined={parties?.combined ?? false} help={help(kind)}>
      {content}
    </ReportFrame>
  )
}
