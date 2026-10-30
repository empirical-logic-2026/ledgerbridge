// Amounts and dates the way the dashboard shows them (docs/design/dashboard.md Section 0):
// rupees in Indian grouping (₹16,20,000.00), short in lakhs and crores (₹62.4 L, ₹4.82 Cr),
// dates DD-MMM-YYYY. The API sends amounts as decimal strings; they are handled as whole
// numbers of 1/10,000 rupee (BigInt), never as floating-point numbers, so nothing is lost
// to rounding. Only charts get plain numbers (`toLakhs`), for drawing.

const SCALE = 4 // the API's amounts have 4 decimal places (DECIMAL(20,4))
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const LAKH = 10n ** 5n
const CRORE = 10n ** 7n

/** "-1234.5" -> -12345000n (in 1/10,000). Throws on anything that isn't a decimal number. */
export function toScaled(amount: string): bigint {
  const match = /^(-?)(\d+)(?:\.(\d+))?$/.exec(amount.trim())
  if (!match) throw new Error(`Not an amount: ${amount}`)
  const [, sign, whole, fraction = ''] = match
  const digits = (fraction + '0'.repeat(SCALE)).slice(0, SCALE)
  const value = BigInt(whole) * 10n ** BigInt(SCALE) + BigInt(digits)
  return sign ? -value : value
}

/** `value / divisor` rounded half away from zero. */
function divideRounded(value: bigint, divisor: bigint): bigint {
  const half = divisor / 2n
  return value < 0n ? -((-value + half) / divisor) : (value + half) / divisor
}

/** "1620000" -> "16,20,000": the last three digits, then pairs. */
export function indianGrouping(digits: string): string {
  if (digits.length <= 3) return digits
  const head = digits.slice(0, -3)
  const pairs = head.replace(/\B(?=(\d{2})+(?!\d))/g, ',')
  return `${pairs},${digits.slice(-3)}`
}

/** A non-negative value in 1/10^places units, written with that many decimals. */
function withDecimals(value: bigint, places: number): string {
  const text = value.toString().padStart(places + 1, '0')
  const whole = text.slice(0, text.length - places)
  return places ? `${indianGrouping(whole)}.${text.slice(-places)}` : indianGrouping(whole)
}

/** The exact amount: "₹16,20,000.00", "-₹500.50". */
export function formatExact(amount: string): string {
  const paise = divideRounded(toScaled(amount), 100n) // 2 decimals
  const sign = paise < 0n ? '-' : ''
  return `${sign}₹${withDecimals(paise < 0n ? -paise : paise, 2)}`
}

/** Short: "₹4.82 Cr" (2 decimals), "₹62.4 L" (1 decimal), below a lakh "₹45,300". */
export function formatCompact(amount: string): string {
  const scaled = toScaled(amount)
  const rupees = divideRounded(scaled, 10n ** BigInt(SCALE))
  const size = rupees < 0n ? -rupees : rupees
  const sign = scaled < 0n ? '-' : ''
  const unscale = 10n ** BigInt(SCALE)
  if (size >= CRORE) {
    const hundredths = divideRounded(scaled < 0n ? -scaled : scaled, (CRORE * unscale) / 100n)
    return `${sign}₹${withDecimals(hundredths, 2)} Cr`
  }
  if (size >= LAKH) {
    const tenths = divideRounded(scaled < 0n ? -scaled : scaled, (LAKH * unscale) / 10n)
    return `${sign}₹${withDecimals(tenths, 1)} L`
  }
  return `${rupees < 0n ? '-' : ''}₹${indianGrouping(size.toString())}`
}

/** For charts only: the amount in lakhs as a number (drawing, never sums or display). */
export function toLakhs(amount: string): number {
  return Number(divideRounded(toScaled(amount), LAKH * 100n)) / 100
}

/** "2026-09-30" -> "30-Sep-2026" (dates as text: no time zone can shift them). */
export function formatDate(iso: string): string {
  const [year, month, day] = iso.slice(0, 10).split('-')
  return `${day}-${MONTHS[Number(month) - 1]}-${year}`
}

/** "2026-09-01" -> "Sep-2026". */
export function formatMonth(iso: string): string {
  const [year, month] = iso.slice(0, 7).split('-')
  return `${MONTHS[Number(month) - 1]}-${year}`
}

/** "5 min ago", "3 h ago", "2 days ago", from a UTC time the API sends without a zone. */
export function timeAgo(isoUtc: string, now: Date = new Date()): string {
  const at = new Date(/[zZ]|[+-]\d\d:\d\d$/.test(isoUtc) ? isoUtc : `${isoUtc}Z`)
  const minutes = Math.max(0, Math.round((now.getTime() - at.getTime()) / 60_000))
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes} min ago`
  const hours = Math.round(minutes / 60)
  if (hours < 48) return `${hours} h ago`
  return `${Math.round(hours / 24)} days ago`
}
