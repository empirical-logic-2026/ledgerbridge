import * as echarts from 'echarts'
import { useEffect, useRef } from 'react'

interface EChartProps {
  option: echarts.EChartsOption
  height?: number
  dark?: boolean // ECharts' dark theme; give the component a new `key` when it changes
}

/** Thin wrapper that owns one ECharts instance for the lifetime of the component. */
export function EChart({ option, height = 300, dark = false }: EChartProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<echarts.ECharts | null>(null)

  useEffect(() => {
    if (!containerRef.current) return
    const chart = echarts.init(containerRef.current, dark ? 'dark' : undefined)
    chartRef.current = chart
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

  return <div ref={containerRef} style={{ width: '100%', height }} />
}
