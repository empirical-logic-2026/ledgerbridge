// The Overview app: the year's sales, purchases, gross and net profit, the balances of cash
// and bank, receivables and payables as at the date, monthly sales as a chart, and each
// company's data health (last sync, latest validation). Figures: core/overview.py.
// Short amounts on the cards (₹4.82 Cr), the exact amount on hover.

import { Alert, Card, Flex, Skeleton, Tag, Tooltip, Typography } from 'antd'
import type { EChartsOption } from 'echarts'
import type { Company, FinancialYear, Overview } from '../../api/types.ts'
import { EChart } from '../../components/EChart.tsx'
import { formatCompact, formatDate, formatExact, formatMonth, timeAgo, toLakhs } from '../../format.ts'
import { COMBINED_LABEL, COMBINED_NOTE } from '../../shell/CompanySwitcher.tsx'
import { palette } from '../../theme.ts'

interface Props {
  companies: Company[] // the selected ones
  year: FinancialYear | undefined
  overview: Overview | undefined
  loading: boolean
  error: Error | null
  dark: boolean
}

interface Figure {
  label: string
  caption: string
  value: string | null | undefined
  missing?: string // why there is no value
}

function greeting(now: Date = new Date()): string {
  const hour = now.getHours()
  if (hour < 12) return 'Good morning'
  if (hour < 17) return 'Good afternoon'
  return 'Good evening'
}

function FigureCard({ figure }: { figure: Figure }) {
  const value = figure.value
  return (
    <Card size="small" className="figure-card">
      <Typography.Text type="secondary">{figure.label}</Typography.Text>
      <div className="figure-value">
        {value === null || value === undefined ? (
          <Tooltip title={figure.missing}>
            <span>—</span>
          </Tooltip>
        ) : (
          <Tooltip title={formatExact(value)}>
            <span>{formatCompact(value)}</span>
          </Tooltip>
        )}
      </div>
      <Typography.Text type="secondary" className="figure-caption">
        {value === null && figure.missing ? figure.missing : figure.caption}
      </Typography.Text>
    </Card>
  )
}

function salesChart(overview: Overview, dark: boolean): EChartsOption {
  const months = overview.monthly_sales
  return {
    backgroundColor: 'transparent',
    grid: { left: 56, right: 16, top: 24, bottom: 32 },
    tooltip: {
      trigger: 'axis',
      formatter: (params: unknown) => {
        const [point] = params as { dataIndex: number }[]
        const month = months[point.dataIndex]
        return `${formatMonth(month.month)}<br/>${formatExact(month.net_sales)}`
      },
    },
    xAxis: { type: 'category', data: months.map((m) => formatMonth(m.month)) },
    yAxis: { type: 'value', name: '₹ lakh', nameTextStyle: { align: 'right' } },
    series: [
      {
        type: 'bar',
        name: 'Sales',
        data: months.map((m) => toLakhs(m.net_sales)),
        itemStyle: { color: dark ? '#2DD4BF' : palette.primary, borderRadius: [4, 4, 0, 0] },
      },
    ],
  }
}

function HealthList({ companies }: { companies: Company[] }) {
  return (
    <Flex vertical gap={10}>
      {companies.map((c) => {
        const h = c.health
        const status =
          h.validation_status === 'passed' ? (
            <Tag color="success">Checks passed</Tag>
          ) : h.validation_status === 'failed' ? (
            <Tag color="error">Checks failed</Tag>
          ) : h.validation_status === 'running' ? (
            <Tag color="processing">Checking</Tag>
          ) : (
            <Tag>Not checked yet</Tag>
          )
        return (
          <Flex key={c.id} justify="space-between" align="center" gap={8} wrap>
            <Typography.Text strong>{c.name}</Typography.Text>
            <Flex gap={8} align="center" wrap>
              {status}
              <Typography.Text type="secondary">
                {h.validated_as_of ? `as at ${formatDate(h.validated_as_of)} · ` : ''}
                {h.last_sync_at ? `synced ${timeAgo(h.last_sync_at)}` : 'never synced'}
              </Typography.Text>
            </Flex>
          </Flex>
        )
      })}
    </Flex>
  )
}

export function OverviewApp({ companies, year, overview, loading, error, dark }: Props) {
  if (error) return <Alert type="error" showIcon message="The figures couldn't be loaded." description={error.message} />
  const period = overview
    ? `${year?.label ?? ''}, ${formatDate(overview.period_start)} to ${formatDate(overview.as_of)}`
    : ''
  const asAt = overview ? `As at ${formatDate(overview.as_of)}` : ''
  const noStatement = 'Not available: no statement is stored for this date.'
  const figures: Figure[] = [
    { label: 'Sales', caption: period, value: overview?.sales },
    { label: 'Purchases', caption: period, value: overview?.purchases },
    { label: 'Gross profit', caption: period, value: overview?.gross_profit, missing: noStatement },
    { label: 'Net profit', caption: period, value: overview?.net_profit, missing: noStatement },
    { label: 'Cash & bank', caption: asAt, value: overview?.cash_and_bank },
    { label: 'Who owes us', caption: `Receivables · ${asAt}`, value: overview?.receivables },
    { label: 'Who we owe', caption: `Payables · ${asAt}`, value: overview?.payables },
  ]
  return (
    <Flex vertical gap={16}>
      <div>
        <Typography.Title level={3} style={{ margin: 0 }}>
          {greeting()}! Here's how your business is doing.
        </Typography.Title>
        <Typography.Text type="secondary">
          Figures from your books as last synced. Hover over an amount to see it in full.
          {overview?.combined ? (
            <>
              {' '}
              <Tag color="cyan">{COMBINED_LABEL}</Tag>
              {COMBINED_NOTE}.
            </>
          ) : null}
        </Typography.Text>
      </div>
      {loading && !overview ? (
        <Skeleton active />
      ) : (
        <>
          <div className="figures">
            {figures.map((f) => (
              <FigureCard key={f.label} figure={f} />
            ))}
          </div>
          <div className="overview-row">
            <Card title="Sales, month by month (₹ lakh)" className="overview-chart">
              {overview && overview.monthly_sales.length > 0 ? (
                <EChart key={dark ? 'dark' : 'light'} option={salesChart(overview, dark)} dark={dark} />
              ) : (
                <Typography.Text type="secondary">No sales in this period.</Typography.Text>
              )}
            </Card>
            <Card title="Data health" className="overview-health">
              <HealthList companies={companies} />
            </Card>
          </div>
        </>
      )}
    </Flex>
  )
}
