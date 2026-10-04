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
