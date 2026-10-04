/**
 * The indicators drawn under the chart, computed the way the backend's rule steps
 * compute them, so the RSI a rule crosses is the RSI on screen: Wilder's RSI and
 * MACD from exponential averages seeded with a simple mean.
 *
 * Each result is aligned to the input - one entry per candle, null until the
 * indicator has enough bars to mean anything.
 */

export function ema(values: number[], period: number): (number | null)[] {
  const out: (number | null)[] = new Array(values.length).fill(null)
  if (values.length < period) return out
  const k = 2 / (period + 1)
  let prev = values.slice(0, period).reduce((a, b) => a + b, 0) / period
  out[period - 1] = prev
  for (let i = period; i < values.length; i++) {
    prev = values[i] * k + prev * (1 - k)
    out[i] = prev
  }
  return out
}

export function sma(values: number[], period: number): (number | null)[] {
  const out: (number | null)[] = new Array(values.length).fill(null)
  let sum = 0
  for (let i = 0; i < values.length; i++) {
    sum += values[i]
    if (i >= period) sum -= values[i - period]
    if (i >= period - 1) out[i] = sum / period
  }
  return out
}

export function rsi(closes: number[], period = 14): (number | null)[] {
  const out: (number | null)[] = new Array(closes.length).fill(null)
  if (closes.length <= period) return out
  let gain = 0
  let loss = 0
  for (let i = 1; i <= period; i++) {
    const d = closes[i] - closes[i - 1]
    if (d >= 0) gain += d
    else loss -= d
  }
  gain /= period
  loss /= period
  const value = () => (loss === 0 ? 100 : 100 - 100 / (1 + gain / loss))
  out[period] = value()
  for (let i = period + 1; i < closes.length; i++) {
    const d = closes[i] - closes[i - 1]
    gain = (gain * (period - 1) + Math.max(d, 0)) / period
    loss = (loss * (period - 1) + Math.max(-d, 0)) / period
    out[i] = value()
  }
  return out
}

export interface MacdPoint {
  macd: number
  signal: number
  histogram: number
}

export function macd(closes: number[], fast = 12, slow = 26, signal = 9): (MacdPoint | null)[] {
  const f = ema(closes, fast)
  const s = ema(closes, slow)
  const line = closes.map((_, i) => (f[i] !== null && s[i] !== null ? (f[i] as number) - (s[i] as number) : null))
  const first = line.findIndex((v) => v !== null)
  const out: (MacdPoint | null)[] = new Array(closes.length).fill(null)
  if (first < 0) return out
  const sig = ema(line.slice(first) as number[], signal)
  for (let i = first; i < closes.length; i++) {
    const sv = sig[i - first]
    if (sv === null) continue
    const m = line[i] as number
    out[i] = { macd: m, signal: sv, histogram: m - sv }
  }
  return out
}

// --- what is on the chart -----------------------------------------------------

/** One indicator on the chart: averages ride on the price, RSI and MACD get panes. */
export type IndicatorSpec =
  | { kind: "ema"; period: number }
  | { kind: "sma"; period: number }
  | { kind: "rsi"; period: number }
  | { kind: "macd" }

export const DEFAULT_SPECS: IndicatorSpec[] = [{ kind: "rsi", period: 14 }, { kind: "macd" }]

export const PRESETS: IndicatorSpec[] = [
  { kind: "ema", period: 9 },
  { kind: "ema", period: 21 },
  { kind: "ema", period: 50 },
  { kind: "ema", period: 200 },
  { kind: "sma", period: 20 },
  { kind: "sma", period: 50 },
  { kind: "rsi", period: 14 },
  { kind: "macd" },
]

export function specKey(s: IndicatorSpec): string {
  return s.kind === "macd" ? "macd" : `${s.kind}:${s.period}`
}

export function specLabel(s: IndicatorSpec): string {
  return s.kind === "macd" ? "MACD 12 26 9" : `${s.kind.toUpperCase()} ${s.period}`
}

export function isOverlay(s: IndicatorSpec): s is { kind: "ema" | "sma"; period: number } {
  return s.kind === "ema" || s.kind === "sma"
}

/** Add specs not already on, keeping the order they were added in. */
export function withSpecs(current: IndicatorSpec[], add: IndicatorSpec[]): IndicatorSpec[] {
  const seen = new Set(current.map(specKey))
  const out = [...current]
  for (const s of add) {
    if (seen.has(specKey(s))) continue
    seen.add(specKey(s))
    out.push(s)
  }
  return out
}

export function withoutSpecs(current: IndicatorSpec[], remove: IndicatorSpec[] | "all"): IndicatorSpec[] {
  if (remove === "all") return []
  // "remove ema" with no period takes every EMA off.
  return current.filter(
    (c) =>
      !remove.some((r) =>
        r.kind === c.kind && (r.kind === "macd" || (r as { period: number }).period === 0 || specKey(r) === specKey(c)),
      ),
  )
}

export interface IndicatorRequest {
  specs: IndicatorSpec[]
  /** Specs with period 0 mean "every one of that kind". */
  remove: boolean
  /** The message is only about drawing, so the chart can answer it without the server. */
  drawOnly: boolean
}

const DRAW = /\b(show|mark|add|draw|plot|put|overlay|display|enable|apply|lagao|laga|lga|lagado|dikhao|dikha|dikhado|chart\s+pe|chart\s+par)\b/
const REMOVE = /\b(remove|hide|clear|delete|disable|hatao|hata|hatado|band)\b/
const ASKS = /\?|\b(alert|notify|when|whenever|jab|is there|are there|any|kya|where|why|how|backtest|strategy|rule|buy|sell|trade)\b/
const NUMS = String.raw`(\d{1,3}(?:\s*(?:,|and|&|\/|aur|or|n)\s*\d{1,3})*)`

function numbersAround(text: string, at: number, end: number): number[] {
  const after = text.slice(end).match(new RegExp(String.raw`^\s*(?:\(|period\s*)?\s*` + NUMS))
  const before = text.slice(0, at).match(new RegExp(NUMS + String.raw`\s*(?:period\s*)?$`))
  const found = [after?.[1], before?.[1]].filter(Boolean).join(",")
  return Array.from(found.matchAll(/\d{1,3}/g), (m) => Number(m[0])).filter((n) => n >= 2 && n <= 400)
}

/**
 * What a chat message asks to draw: "show EMA 9 and 21", "9/21 ema crossover",
 * "RSI lagao", "remove macd". Empty `specs` when it names no indicator.
 */
export function parseIndicatorRequest(message: string): IndicatorRequest {
  const text = message.toLowerCase()
  const remove = REMOVE.test(text) && !DRAW.test(text.replace(REMOVE, ""))
  const specs: IndicatorSpec[] = []
  for (const m of text.matchAll(/\b(exponential moving average|simple moving average|moving average|ema|sma|ma)\b/g)) {
    const word = m[1]
    const kind: "ema" | "sma" = word === "ema" || word.startsWith("exponential") ? "ema" : "sma"
    const periods = numbersAround(text, m.index!, m.index! + word.length)
    // A bare "ma" is too common a syllable to act on without a period.
    if (periods.length === 0 && word === "ma") continue
    if (periods.length === 0) specs.push({ kind, period: remove ? 0 : kind === "ema" ? 20 : 50 })
    for (const p of periods) specs.push({ kind, period: p })
  }
  for (const m of text.matchAll(/\brsi\b\s*\(?\s*(\d{1,2})?/g)) {
    const p = m[1] ? Number(m[1]) : 14
    specs.push({ kind: "rsi", period: remove && !m[1] ? 0 : p >= 2 ? p : 14 })
  }
  if (/\bmacd\b/.test(text)) specs.push({ kind: "macd" })
  const unique = withSpecs([], specs)
  const command = DRAW.test(text) || remove
  return { specs: unique, remove, drawOnly: unique.length > 0 && command && !ASKS.test(text) }
}

/** Window event the chat uses to put indicators on (or take them off) the chart. */
export const INDICATOR_EVENT = "vt:indicators"

export interface IndicatorEventDetail {
  add?: IndicatorSpec[]
  remove?: IndicatorSpec[] | "all"
}

export function sendIndicators(detail: IndicatorEventDetail) {
  window.dispatchEvent(new CustomEvent<IndicatorEventDetail>(INDICATOR_EVENT, { detail }))
}
