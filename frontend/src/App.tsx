import { useQuery } from '@tanstack/react-query'
import type { EChartsOption } from 'echarts'
import { Card, Descriptions, Layout, Space, Tag, Typography } from 'antd'
import { getJson, type Health } from './api/client.ts'
import { EChart } from './components/EChart.tsx'

// Placeholder data so the chart wiring is visible; real figures arrive with M6/M7.
const sampleChart: EChartsOption = {
  title: { text: 'Sample chart (placeholder)', left: 'center' },
  xAxis: { type: 'category', data: ['Apr', 'May', 'Jun', 'Jul'] },
  yAxis: { type: 'value' },
  series: [{ type: 'bar', data: [3, 5, 4, 6] }],
}

function HealthCard() {
  const { data, isPending, isError } = useQuery({
    queryKey: ['health'],
    queryFn: () => getJson<Health>('/health'),
  })

  let status = <Tag>checking</Tag>
  if (isError) status = <Tag color="error">unreachable</Tag>
  else if (!isPending) status = <Tag color="success">{data.status}</Tag>

  return (
    <Card title="Data plane API">
      <Descriptions column={1} size="small">
        <Descriptions.Item label="Status">{status}</Descriptions.Item>
        <Descriptions.Item label="Environment">{data?.env ?? '—'}</Descriptions.Item>
        <Descriptions.Item label="Version">{data?.version ?? '—'}</Descriptions.Item>
      </Descriptions>
    </Card>
  )
}

export default function App() {
  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Layout.Header>
        <Typography.Title level={4} style={{ color: '#fff', margin: '14px 0' }}>
          LedgerBridge
        </Typography.Title>
      </Layout.Header>
      <Layout.Content style={{ padding: 24 }}>
        <Space direction="vertical" size="large" style={{ width: '100%' }}>
          <HealthCard />
          <Card>
            <EChart option={sampleChart} />
          </Card>
        </Space>
      </Layout.Content>
    </Layout>
  )
}
