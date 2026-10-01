export const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"

export interface Candle {
  time: string
  open: number
  high: number
  low: number
  close: number
  volume: number
}

export interface LiquidityLevel {
  price: number
  strength: "strong" | "medium" | "weak" | string
  test_count?: number
  distance_pct?: number
}

export interface LiquidityData {
  current_price: number
  support_levels: LiquidityLevel[]
  resistance_levels: LiquidityLevel[]
}

export async function fetchOHLC(
  symbol: string,
  timeframe = "1h",
  limit = 120,
): Promise<Candle[]> {
  const res = await fetch(
    `${API_BASE}/api/ohlc/${symbol}?timeframe=${timeframe}&limit=${limit}`,
  )
  if (!res.ok) throw new Error(`OHLC request failed (${res.status})`)
  return res.json()
}

export const TIMEFRAMES = ["1m", "5m", "15m", "1h", "1d"] as const
export type Timeframe = (typeof TIMEFRAMES)[number]

/** A candle from /api/candles. `time` is the open time in unix milliseconds. */
export interface MsCandle {
  time: number
  open: number
  high: number
  low: number
  close: number
  volume: number
}

async function readError(res: Response, fallback: string): Promise<string> {
  try {
    const body = await res.json()
    return body?.detail ?? fallback
  } catch {
    return fallback
  }
}

export async function fetchCandles(
  symbol: string,
  timeframe: Timeframe = "1h",
  limit = 1000,
  signal?: AbortSignal,
): Promise<MsCandle[]> {
  const res = await fetch(
    `${API_BASE}/api/candles/${symbol}?timeframe=${timeframe}&limit=${limit}`,
    { signal },
  )
  if (!res.ok) {
    throw new Error(await readError(res, `Could not load ${symbol} ${timeframe}`))
  }
  return res.json()
}

/** Levels computed from only the candles inside the visible window. */
export async function analyseLevels(
  params: { symbol: string; timeframe: Timeframe; from?: number; to?: number },
  signal?: AbortSignal,
): Promise<LiquidityData> {
  const res = await fetch(`${API_BASE}/api/analysis/levels`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
    signal,
  })
  if (!res.ok) {
    throw new Error(await readError(res, "Could not analyse this range"))
  }
  return res.json()
}

/** Adaptive precision - these symbols span $64,000 to $0.069. */
export function formatPrice(price: number): string {
  const digits = price >= 100 ? 2 : price >= 1 ? 3 : 5
  return price.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
}
