/**
 * Direct Binance access for the landing page.
 *
 * The marketing page deliberately does not depend on our own API: it should
 * still show a live market if the backend is down or mid-deploy.
 */

const REST = "https://api.binance.com/api/v3"
const WS = "wss://stream.binance.com:9443"

export interface Kline {
  time: number
  open: number
  high: number
  low: number
  close: number
}

export interface Ticker {
  symbol: string
  price: number
  changePct: number
}

export async function fetchKlines(
  symbol: string,
  interval = "1h",
  limit = 90,
): Promise<Kline[]> {
  const res = await fetch(
    `${REST}/klines?symbol=${symbol}&interval=${interval}&limit=${limit}`,
  )
  if (!res.ok) throw new Error(`klines ${res.status}`)
  const rows: any[][] = await res.json()
  return rows.map((r) => ({
    time: r[0],
    open: Number(r[1]),
    high: Number(r[2]),
    low: Number(r[3]),
    close: Number(r[4]),
  }))
}

/** Reconnecting socket. Returns a disposer. */
function openSocket(path: string, onMessage: (data: any) => void): () => void {
  let socket: WebSocket | null = null
  let retry: ReturnType<typeof setTimeout> | undefined
  let attempts = 0
  let disposed = false

  const connect = () => {
    if (disposed) return
    socket = new WebSocket(`${WS}${path}`)
    socket.onopen = () => {
      attempts = 0
    }
    socket.onmessage = (event) => {
      try {
        onMessage(JSON.parse(event.data))
      } catch {
        /* ignore malformed frames */
      }
    }
    socket.onerror = () => socket?.close()
    socket.onclose = () => {
      if (disposed) return
      attempts += 1
      retry = setTimeout(connect, Math.min(30000, 1000 * 2 ** attempts))
    }
  }

  connect()
  return () => {
    disposed = true
    if (retry) clearTimeout(retry)
    socket?.close()
  }
}

/** Streams the open candle for one symbol. */
export function subscribeKline(
  symbol: string,
  interval: string,
  onCandle: (candle: Kline, closed: boolean) => void,
): () => void {
  return openSocket(`/ws/${symbol.toLowerCase()}@kline_${interval}`, (msg) => {
    const k = msg?.k
    if (!k) return
    onCandle(
      {
        time: k.t,
        open: Number(k.o),
        high: Number(k.h),
        low: Number(k.l),
        close: Number(k.c),
      },
      Boolean(k.x),
    )
  })
}

/** Streams 24h price + change for several symbols at once. */
export function subscribeTickers(
  symbols: string[],
  onTicker: (ticker: Ticker) => void,
): () => void {
  const streams = symbols.map((s) => `${s.toLowerCase()}@miniTicker`).join("/")
  return openSocket(`/stream?streams=${streams}`, (msg) => {
    const d = msg?.data
    if (!d) return
    const open = Number(d.o)
    const price = Number(d.c)
    onTicker({
      symbol: d.s,
      price,
      changePct: open ? ((price - open) / open) * 100 : 0,
    })
  })
}

export function formatUsd(value: number): string {
  const digits = value >= 100 ? 2 : value >= 1 ? 3 : 5
  return value.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
}
