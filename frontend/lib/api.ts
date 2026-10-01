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

/** Adaptive precision - these symbols span $64,000 to $0.069. */
export function formatPrice(price: number): string {
  const digits = price >= 100 ? 2 : price >= 1 ? 3 : 5
  return price.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
}
