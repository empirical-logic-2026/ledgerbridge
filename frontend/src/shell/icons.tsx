// The few icons the dashboard needs, drawn inline (no icon package: no new dependency).

const common = { width: 18, height: 18, viewBox: '0 0 24 24', fill: 'currentColor', 'aria-hidden': true }
const outline = { ...common, fill: 'none', stroke: 'currentColor', strokeWidth: 2, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const }

export function LogoIcon() {
  return (
    <svg {...outline} width={22} height={22}>
      <path d="M3 3v18h18" />
      <path d="M7 15l4-4 3 3 5-6" />
    </svg>
  )
}

export function ReportsIcon() {
  return (
    <svg {...outline} width={26} height={26}>
      <path d="M6 20V10M12 20V4M18 20v-7" />
    </svg>
  )
}

export function SunIcon() {
  return (
    <svg {...common}>
      <circle cx="12" cy="12" r="4.5" />
      <path d="M11 1h2v3h-2zM11 20h2v3h-2zM1 11h3v2H1zM20 11h3v2h-3zM4.2 2.8l2.1 2.1-1.4 1.4-2.1-2.1zM17.7 17.7l2.1 2.1-1.4 1.4-2.1-2.1zM2.8 19.8l2.1-2.1 1.4 1.4-2.1 2.1zM17.7 6.3l2.1-2.1 1.4 1.4-2.1 2.1z" />
    </svg>
  )
}

export function MoonIcon() {
  return (
    <svg {...common}>
      <path d="M20.5 14.2A8.5 8.5 0 0 1 9.8 3.5 8.5 8.5 0 1 0 20.5 14.2z" />
    </svg>
  )
}
