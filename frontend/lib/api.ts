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

export const STRICTNESS = ["strict", "balanced", "loose"] as const
export type Strictness = (typeof STRICTNESS)[number]

/** Which size of structure to hunt for. Independent of strictness. */
export const PATTERN_SCALES = ["swing", "scalp", "both"] as const
export type PatternScale = (typeof PATTERN_SCALES)[number]

/** Which prices pattern geometry is measured on. Breaks are always closes. */
export const SOURCES = ["wick", "close"] as const
export type PatternSource = (typeof SOURCES)[number]

/** Where a pattern is in its life, judged against the latest close. */
export type PatternState = "forming" | "approaching" | "confirmed"

export interface PatternPoint {
  time: number
  price: number
  index: number
}

export interface Pattern {
  kind: "W" | "M"
  state: PatternState
  confidence: number
  components: { similarity: number; depth: number; symmetry: number }
  /** Keyed low1/peak/low2 for a W, high1/trough/high2 for an M. */
  points: Record<string, PatternPoint>
  neckline: number
  target: number
}

export interface PatternResponse {
  symbol: string
  timeframe: string
  strictness: Strictness
  sample_size: number
  total_found: number
  patterns: Pattern[]
}

/** The three points of a pattern in chronological order, whatever its kind. */
export function patternPoints(pattern: Pattern): PatternPoint[] {
  return Object.values(pattern.points).sort((a, b) => a.index - b.index)
}

export async function analysePatterns(
  params: {
    symbol: string
    timeframe: Timeframe
    from?: number
    to?: number
    strictness?: Strictness
    source?: PatternSource
    scale?: PatternScale
  },
  signal?: AbortSignal,
): Promise<PatternResponse> {
  const res = await fetch(`${API_BASE}/api/analysis/patterns`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
    signal,
  })
  if (!res.ok) {
    throw new Error(await readError(res, "Could not detect patterns in this range"))
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
