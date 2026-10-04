/**
 * Robinhood Stock Tokens: what the watchlist lists and the stock chart draws.
 *
 * Crypto candles come from Binance. No exchange we read lists stocks, so a stock's
 * candles are built from the swaps in its own Uniswap pool on Robinhood Chain - the
 * same pool a stock vault trades through - as indexed by GeckoTerminal. That makes
 * the chart a chart of the market the vault actually fills in, which is the honest
 * one to show beside a "trade in vault" button.
 *
 * Pools are the deepest USDG pool for each token, the same tier the factory routes
 * through (contracts/src/Addresses.sol). Feeds are the Chainlink feeds the vault
 * prices against; they follow US market hours.
 */
import type { Timeframe } from "@/lib/api"
import type { Ticker } from "@/lib/binance"

export interface Stock {
  symbol: string
  name: string
  /** The vault market, as the factory and the server name it. */
  market: string
  token: `0x${string}`
  pool: `0x${string}`
  /** Uniswap fee tier of the pool, in percent. */
  feePct: number
  feed: `0x${string}`
}

export const STOCKS: Stock[] = [
  {
    symbol: "NVDA",
    name: "NVIDIA",
    market: "NVDA/USDG",
    token: "0xd0601CE157Db5bdC3162BbaC2a2C8aF5320D9EEC",
    pool: "0xd4eb21209c4d6093f80b5b84f5c45cc093ea14a3",
    feePct: 0.05,
    feed: "0x379EC4f7C378F34a1B47E4F3cbeBCbAC3E8E9F15",
  },
  {
    symbol: "TSLA",
    name: "Tesla",
    market: "TSLA/USDG",
    token: "0x322F0929c4625eD5bAd873c95208D54E1c003b2d",
    pool: "0xf4acdaeeb7022862a763c9b1b885e11191c889e3",
    feePct: 0.3,
    feed: "0x4A1166a659A55625345e9515b32adECea5547C38",
  },
  {
    symbol: "AAPL",
    name: "Apple",
    market: "AAPL/USDG",
    token: "0xaF3D76f1834A1d425780943C99Ea8A608f8a93f9",
    pool: "0xaae0d815ee56e4092a5e5c2911e676fea50b2d6d",
    feePct: 0.05,
    feed: "0x6B22A786bAa607d76728168703a39Ea9C99f2cD0",
  },
  {
    symbol: "SPY",
    name: "S&P 500 ETF",
    market: "SPY/USDG",
    token: "0x117cc2133c37B721F49dE2A7a74833232B3B4C0C",
    pool: "0xa7bb1ac63bbab0c44316e6c8c455213441689167",
    feePct: 0.05,
    feed: "0x319724394D3A0e3669269846abE664Cd621f9f6A",
  },
  {
    symbol: "QQQ",
    name: "Nasdaq-100 ETF",
    market: "QQQ/USDG",
    token: "0xD5f3879160bc7c32ebb4dC785F8a4F505888de68",
    pool: "0xd60a5d14db690b7afad71f76b108071d7175597d",
    feePct: 0.05,
    feed: "0x80901d846d5D7B030F26B480776EE3b29374C2ae",
  },
]

export function stockFor(symbol: string): Stock | null {
  return STOCKS.find((s) => s.symbol === symbol) ?? null
}

export function isStock(symbol: string): boolean {
  return stockFor(symbol) !== null
}

const GECKO = "https://api.geckoterminal.com/api/v2/networks/robinhood"

/** GeckoTerminal's candle buckets for each timeframe the app offers. */
export const GECKO_TIMEFRAME: Record<Timeframe, { unit: "minute" | "hour" | "day"; aggregate: number }> = {
  "1m": { unit: "minute", aggregate: 1 },
  "5m": { unit: "minute", aggregate: 5 },
  "15m": { unit: "minute", aggregate: 15 },
  "1h": { unit: "hour", aggregate: 1 },
  "4h": { unit: "hour", aggregate: 4 },
  "1d": { unit: "day", aggregate: 1 },
}

export interface StockCandle {
  time: number // seconds
  open: number
  high: number
  low: number
  close: number
  volume: number // USD
}

export function candlesUrl(stock: Stock, timeframe: Timeframe, limit = 300): string {
  const { unit, aggregate } = GECKO_TIMEFRAME[timeframe]
  // token= prices the stock rather than the pool's other side, in USD.
  return `${GECKO}/pools/${stock.pool}/ohlcv/${unit}?aggregate=${aggregate}&limit=${limit}&currency=usd&token=${stock.token}`
}

/** Rows arrive newest first as [t, o, h, l, c, v]; the chart wants oldest first. */
export function parseCandles(body: unknown): StockCandle[] {
  const rows = (body as { data?: { attributes?: { ohlcv_list?: number[][] } } })?.data?.attributes?.ohlcv_list ?? []
  return rows
    .filter((r) => Array.isArray(r) && r.length >= 6 && r.every((x) => Number.isFinite(x)))
    .map(([time, open, high, low, close, volume]) => ({ time, open, high, low, close, volume }))
    .sort((a, b) => a.time - b.time)
    .filter((c, i, all) => i === 0 || c.time !== all[i - 1].time)
}

export async function fetchStockCandles(stock: Stock, timeframe: Timeframe): Promise<StockCandle[]> {
  const res = await fetch(candlesUrl(stock, timeframe), { headers: { Accept: "application/json" } })
  if (!res.ok) throw new Error(`Pool candles unavailable (${res.status})`)
  return parseCandles(await res.json())
}

/** Every stock's price, 24h change and 24h pool volume, in one request. */
export function quotesUrl(): string {
  return `${GECKO}/pools/multi/${STOCKS.map((s) => s.pool).join(",")}`
}

export function parseQuotes(body: unknown): Record<string, Ticker> {
  const out: Record<string, Ticker> = {}
  const pools = (body as { data?: { id: string; attributes: Record<string, unknown> }[] })?.data ?? []
  for (const p of pools) {
    const address = p.id.split("_").pop()?.toLowerCase()
    const stock = STOCKS.find((s) => s.pool.toLowerCase() === address)
    if (!stock) continue
    const a = p.attributes as {
      base_token_price_usd?: string
      price_change_percentage?: { h24?: string }
      volume_usd?: { h24?: string }
    }
    const price = Number(a.base_token_price_usd)
    if (!Number.isFinite(price)) continue
    out[stock.symbol] = {
      symbol: stock.symbol,
      price,
      changePct: Number(a.price_change_percentage?.h24 ?? 0) || 0,
      quoteVolume: Number(a.volume_usd?.h24 ?? 0) || 0,
    }
  }
  return out
}

export async function fetchStockQuotes(): Promise<Record<string, Ticker>> {
  const res = await fetch(quotesUrl(), { headers: { Accept: "application/json" } })
  if (!res.ok) throw new Error(`Stock prices unavailable (${res.status})`)
  return parseQuotes(await res.json())
}

/**
 * Asks the analysis panel to open the vault sheet on a given market. An event
 * rather than a prop because the sheet lives inside that panel and the chart
 * asking for it is a sibling.
 */
export const OPEN_VAULT_EVENT = "vt:open-vault"

export function openVault(market: string): void {
  window.dispatchEvent(new CustomEvent<{ market: string }>(OPEN_VAULT_EVENT, { detail: { market } }))
}
