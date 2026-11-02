import * as echarts from 'echarts'
import { useEffect, useRef } from 'react'

interface EChartProps {
  option: echarts.EChartsOption
  height?: number
  dark?: boolean // ECharts' dark theme; give the component a new `key` when it changes
  onClick?: (dataIndex: number) => void // a bar or point clicked (e.g. a month opens its register)
}

/** Thin wrapper that owns one ECharts instance for the lifetime of the component. */
export function EChart({ option, height = 300, dark = false, onClick }: EChartProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<echarts.ECharts | null>(null)
  const clickRef = useRef(onClick)

  useEffect(() => {
    clickRef.current = onClick
  }, [onClick])

  useEffect(() => {
    if (!containerRef.current) return
    const chart = echarts.init(containerRef.current, dark ? 'dark' : undefined)
    chartRef.current = chart
    chart.on('click', (params) => clickRef.current?.(params.dataIndex))
    const observer = new ResizeObserver(() => chart.resize())
    observer.observe(containerRef.current)
    return () => {
      observer.disconnect()
      chart.dispose()
      chartRef.current = null
    }
  }, [dark])

  useEffect(() => {
    chartRef.current?.setOption(option, { notMerge: true })
  }, [option])

  return <div ref={containerRef} style={{ width: '100%', height, cursor: onClick ? 'pointer' : undefined }} />
}
