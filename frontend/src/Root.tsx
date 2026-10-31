// The dashboard's root: the theme (light or dark, remembered in this browser) and today's
// date, around the App.

import { App as AntApp, ConfigProvider } from 'antd'
import { useEffect, useState } from 'react'
import App from './App.tsx'
import { initialMode, saveMode, themeConfig, type Mode } from './theme.ts'

function localToday(): string {
  const now = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
}

export function Root() {
  const [mode, setMode] = useState<Mode>(initialMode)
  const [today] = useState(localToday)
  const [now] = useState(() => new Date())
  useEffect(() => {
    document.documentElement.dataset.mode = mode
  }, [mode])
  const changeMode = (next: Mode) => {
    saveMode(next)
    setMode(next)
  }
  return (
    <ConfigProvider theme={themeConfig(mode)}>
      <AntApp>
        <App mode={mode} onMode={changeMode} today={today} now={now} />
      </AntApp>
    </ConfigProvider>
  )
}
