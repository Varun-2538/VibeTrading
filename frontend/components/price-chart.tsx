"use client"

import { useEffect, useMemo, useState } from "react"
import {
  Bar,
  ComposedChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { fetchOHLC, formatPrice, type Candle, type LiquidityData, type LiquidityLevel } from "@/lib/api"

/*
 * Colour: candles carry NO hue - direction is hollow (up) vs filled (down),
 * the original candlestick convention, which stays readable under every form
 * of colour blindness. That frees the only two hues on the canvas for the
 * liquidity levels. The blue/orange pair is validated against this surface:
 * CVD dE 26.8, normal-vision dE 31.8, both well clear of the floors.
 */
const SUPPORT = "#3987e5"
const RESISTANCE = "#d95926"
const INK = "#c3c2b7"
const INK_MUTED = "#898781"
const GRID = "rgba(255,255,255,0.06)"
const SURFACE = "#17181e"

const CRYPTO_PAIRS = [
  { symbol: "BTCUSDT", name: "Bitcoin" },
  { symbol: "ETHUSDT", name: "Ethereum" },
  { symbol: "BNBUSDT", name: "Binance Coin" },
  { symbol: "SOLUSDT", name: "Solana" },
  { symbol: "XRPUSDT", name: "Ripple" },
  { symbol: "ADAUSDT", name: "Cardano" },
  { symbol: "DOGEUSDT", name: "Dogecoin" },
  { symbol: "DOTUSDT", name: "Polkadot" },
  { symbol: "AVAXUSDT", name: "Avalanche" },
]

/** Strength is encoded by line weight and dash, never by colour alone. */
function strengthStyle(strength: string) {
  if (strength === "strong") return { width: 2, dash: undefined }
  if (strength === "medium") return { width: 2, dash: "7 4" }
  return { width: 1, dash: "2 4" }
}

interface MarkedLevel extends LiquidityLevel {
  kind: "support" | "resistance"
}

interface CandleRow extends Candle {
  label: string
  range: [number, number]
}

/**
 * Recharts has no candlestick mark. We render one via a custom shape on a
 * range Bar: the bar spans low->high, so `y` is the pixel of `high` and
 * `height` covers the whole wick. Any price maps into that box linearly.
 */
function CandleShape(props: any) {
  const { x, y, width, height, payload } = props
  const { open, close, high, low } = payload as CandleRow

  const span = high - low
  const priceToY = (p: number) => (span === 0 ? y + height / 2 : y + ((high - p) / span) * height)

  const yOpen = priceToY(open)
  const yClose = priceToY(close)
  const isUp = close >= open

  const bodyTop = Math.min(yOpen, yClose)
  const bodyHeight = Math.max(Math.abs(yClose - yOpen), 1)
  const centre = x + width / 2
  const bodyWidth = Math.max(width, 1)

  return (
    <g>
      <line x1={centre} x2={centre} y1={y} y2={y + height} stroke={INK} strokeWidth={1} />
      <rect
        x={x}
        y={bodyTop}
        width={bodyWidth}
        height={bodyHeight}
        fill={isUp ? SURFACE : INK}
        stroke={INK}
        strokeWidth={1}
      />
    </g>
  )
}

function CandleTooltip({ active, payload }: any) {
  if (!active || !payload?.length) return null
  const row = payload[0].payload as CandleRow
  const rows: [string, number][] = [
    ["Open", row.open],
    ["High", row.high],
    ["Low", row.low],
    ["Close", row.close],
  ]
  return (
    <div className="rounded-md border border-border bg-card/95 px-3 py-2 shadow-lg backdrop-blur">
      <div className="mb-1 text-xs text-muted-foreground">{row.label}</div>
      <div className="grid grid-cols-2 gap-x-4 gap-y-0.5 text-xs tabular-nums">
        {rows.map(([k, v]) => (
          <div key={k} className="contents">
            <span className="text-muted-foreground">{k}</span>
            <span className="text-right text-foreground">{formatPrice(v)}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

interface PriceChartProps {
  symbol?: string
  onSymbolChange?: (symbol: string) => void
  liquidityData?: { symbol: string; liquidityData: LiquidityData } | null
  onClearLevels?: () => void
}

export default function PriceChart({
  symbol,
  onSymbolChange,
  liquidityData,
  onClearLevels,
}: PriceChartProps) {
  const selected = symbol || "BTCUSDT"
  const [candles, setCandles] = useState<Candle[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [live, setLive] = useState(false)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)

    fetchOHLC(selected)
      .then((data) => {
        if (!cancelled) setCandles(data)
      })
      .catch((e) => {
        if (!cancelled) setError(e.message ?? "Could not load chart data")
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [selected])

  /*
   * Live ticks. The backend only refreshes from Binance every 5 minutes, so
   * polling it would step rather than move. Subscribing to Binance's kline
   * stream directly updates the open candle roughly once a second: close
   * moves, high/low extend, and the body flips hollow/filled as it crosses
   * its open. History and the liquidity levels still come from our own API.
   */
  useEffect(() => {
    if (loading || error) return

    let socket: WebSocket | null = null
    let retry: ReturnType<typeof setTimeout> | undefined
    let attempts = 0
    let disposed = false

    const connect = () => {
      if (disposed) return
      socket = new WebSocket(
        `wss://stream.binance.com:9443/ws/${selected.toLowerCase()}@kline_1h`,
      )

      socket.onopen = () => {
        attempts = 0
        setLive(true)
      }

      socket.onmessage = (event) => {
        let k: any
        try {
          k = JSON.parse(event.data)?.k
        } catch {
          return
        }
        if (!k) return

        const tick: Candle = {
          time: new Date(k.t).toISOString(),
          open: Number(k.o),
          high: Number(k.h),
          low: Number(k.l),
          close: Number(k.c),
          volume: Number(k.v),
        }

        setCandles((prev) => {
          if (!prev.length) return prev
          const lastStart = new Date(prev[prev.length - 1].time).getTime()

          // Same candle still open - replace it in place.
          if (k.t === lastStart) {
            const next = prev.slice()
            next[next.length - 1] = tick
            return next
          }
          // A new hour opened - roll the window forward.
          if (k.t > lastStart) return [...prev.slice(1), tick]
          return prev
        })
      }

      socket.onerror = () => socket?.close()

      socket.onclose = () => {
        setLive(false)
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
      setLive(false)
    }
  }, [selected, loading, error])

  const rows: CandleRow[] = useMemo(
    () =>
      candles.map((c) => ({
        ...c,
        label: new Date(c.time).toLocaleString(undefined, {
          month: "short",
          day: "numeric",
          hour: "2-digit",
        }),
        range: [c.low, c.high] as [number, number],
      })),
    [candles],
  )

  // Only mark levels that belong to the symbol on screen.
  const levels: MarkedLevel[] = useMemo(() => {
    if (!liquidityData || liquidityData.symbol !== selected) return []
    const { support_levels = [], resistance_levels = [] } = liquidityData.liquidityData
    return [
      ...support_levels.map((l) => ({ ...l, kind: "support" as const })),
      ...resistance_levels.map((l) => ({ ...l, kind: "resistance" as const })),
    ]
  }, [liquidityData, selected])

  const spot = rows.length ? rows[rows.length - 1].close : undefined

  // The y-domain must cover the levels too, or a line lands off-canvas.
  const domain = useMemo<[number, number]>(() => {
    if (!rows.length) return [0, 1]
    const prices = [
      ...rows.map((r) => r.low),
      ...rows.map((r) => r.high),
      ...levels.map((l) => l.price),
    ]
    const min = Math.min(...prices)
    const max = Math.max(...prices)
    const pad = (max - min) * 0.06 || max * 0.01
    return [min - pad, max + pad]
  }, [rows, levels])

  const railLevels = useMemo(() => [...levels].sort((a, b) => b.price - a.price), [levels])

  return (
    <div className="flex h-full w-full flex-col bg-card">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <div className="flex items-center gap-3">
          <Select value={selected} onValueChange={(v) => onSymbolChange?.(v)}>
            <SelectTrigger className="w-[240px] border-border bg-secondary">
              <SelectValue placeholder="Select cryptocurrency" />
            </SelectTrigger>
            <SelectContent>
              {CRYPTO_PAIRS.map((c) => (
                <SelectItem key={c.symbol} value={c.symbol}>
                  <div className="flex w-full items-center justify-between">
                    <span className="font-semibold">{c.symbol}</span>
                    <span className="ml-2 text-xs text-muted-foreground">{c.name}</span>
                  </div>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {spot !== undefined && (
            <span className="text-sm tabular-nums text-foreground">${formatPrice(spot)}</span>
          )}
          <Badge variant="outline" className="border-orange-500/20 bg-orange-500/10 text-xs text-orange-500">
            1h
          </Badge>
          <span
            className="flex items-center gap-1.5 text-[11px] text-muted-foreground"
            title={live ? "Streaming live from Binance" : "Not connected to the live feed"}
          >
            <span
              className={`inline-block h-1.5 w-1.5 rounded-full ${
                live ? "animate-pulse bg-emerald-500" : "bg-muted-foreground/40"
              }`}
            />
            {live ? "live" : "offline"}
          </span>
        </div>

        {levels.length > 0 && (
          <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={onClearLevels}>
            Clear {levels.length} level{levels.length === 1 ? "" : "s"}
          </Button>
        )}
      </div>

      <div className="flex min-h-0 flex-1">
        {/* Chart */}
        <div className="relative min-w-0 flex-1">
          {loading && (
            <div className="absolute inset-0 grid place-items-center text-sm text-muted-foreground">
              Loading {selected}…
            </div>
          )}
          {error && !loading && (
            <div className="absolute inset-0 grid place-items-center px-6 text-center text-sm text-muted-foreground">
              {error}
              <br />
              <span className="text-xs">Is the backend running on {"http://localhost:8000"}?</span>
            </div>
          )}
          {!loading && !error && (
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={rows} margin={{ top: 16, right: 68, bottom: 8, left: 8 }}>
                <XAxis
                  dataKey="label"
                  tick={{ fill: INK_MUTED, fontSize: 11 }}
                  axisLine={{ stroke: GRID }}
                  tickLine={false}
                  minTickGap={60}
                />
                <YAxis
                  domain={domain}
                  orientation="right"
                  tick={{ fill: INK_MUTED, fontSize: 11 }}
                  axisLine={false}
                  tickLine={false}
                  width={60}
                  tickFormatter={(v: number) => formatPrice(v)}
                />
                <Tooltip
                  content={<CandleTooltip />}
                  cursor={{ fill: "rgba(255,255,255,0.04)" }}
                  isAnimationActive={false}
                />

                <Bar dataKey="range" shape={<CandleShape />} isAnimationActive={false} />

                {spot !== undefined && (
                  <ReferenceLine
                    y={spot}
                    stroke={INK_MUTED}
                    strokeWidth={1}
                    strokeDasharray="3 3"
                    label={{
                      value: `spot ${formatPrice(spot)}`,
                      position: "right",
                      dy: -6,
                      fill: INK_MUTED,
                      fontSize: 10,
                    }}
                  />
                )}

                {levels.map((level, i) => {
                  const { width, dash } = strengthStyle(level.strength)
                  const colour = level.kind === "support" ? SUPPORT : RESISTANCE
                  return (
                    <ReferenceLine
                      key={`${level.kind}-${level.price}-${i}`}
                      y={level.price}
                      stroke={colour}
                      strokeWidth={width}
                      strokeDasharray={dash}
                      label={{
                        value: `${level.kind === "support" ? "S" : "R"} ${formatPrice(level.price)}`,
                        position: "insideLeft",
                        // Lift the text clear of its own line, and off the axis
                        dy: -6,
                        dx: 4,
                        fill: colour,
                        fontSize: 11,
                      }}
                    />
                  )
                })}
              </ComposedChart>
            </ResponsiveContainer>
          )}
        </div>

        {/* Level rail */}
        <div className="w-[190px] shrink-0 overflow-y-auto border-l border-border px-3 py-3">
          <div className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            Liquidity levels
          </div>

          {railLevels.length === 0 ? (
            <p className="text-xs leading-relaxed text-muted-foreground">
              Ask the assistant for support &amp; resistance, then press{" "}
              <span className="text-foreground">Mark on chart</span>.
            </p>
          ) : (
            <ul className="space-y-1.5">
              {railLevels.map((level, i) => {
                const colour = level.kind === "support" ? SUPPORT : RESISTANCE
                const { dash } = strengthStyle(level.strength)
                const crossesSpot =
                  spot !== undefined &&
                  i > 0 &&
                  railLevels[i - 1].price > spot &&
                  level.price <= spot

                return (
                  <li key={`${level.kind}-${level.price}-${i}`}>
                    {crossesSpot && spot !== undefined && (
                      <div className="mb-1.5 flex items-center gap-2 border-t border-dashed border-border pt-1.5 text-[11px] tabular-nums text-muted-foreground">
                        spot ${formatPrice(spot)}
                      </div>
                    )}
                    <div className="flex items-start gap-2">
                      <svg width="14" height="10" className="mt-1 shrink-0" aria-hidden>
                        <line
                          x1="0"
                          y1="5"
                          x2="14"
                          y2="5"
                          stroke={colour}
                          strokeWidth={strengthStyle(level.strength).width}
                          strokeDasharray={dash}
                        />
                      </svg>
                      <div className="min-w-0">
                        <div className="text-xs tabular-nums text-foreground">
                          {level.kind === "support" ? "S" : "R"} ${formatPrice(level.price)}
                        </div>
                        <div className="text-[11px] text-muted-foreground">
                          {level.strength}
                          {level.test_count ? ` · ${level.test_count} tests` : ""}
                          {level.distance_pct !== undefined ? ` · ${level.distance_pct}%` : ""}
                        </div>
                      </div>
                    </div>
                  </li>
                )
              })}
            </ul>
          )}
        </div>
      </div>

      {/* Legend - identity is never colour alone */}
      <div className="flex flex-wrap items-center gap-x-5 gap-y-1 border-t border-border px-4 py-2 text-[11px] text-muted-foreground">
        <span className="flex items-center gap-1.5">
          <svg width="9" height="13" aria-hidden>
            <rect x="0.5" y="0.5" width="8" height="12" fill={SURFACE} stroke={INK} />
          </svg>
          up (hollow)
        </span>
        <span className="flex items-center gap-1.5">
          <svg width="9" height="13" aria-hidden>
            <rect x="0.5" y="0.5" width="8" height="12" fill={INK} stroke={INK} />
          </svg>
          down (filled)
        </span>
        <span className="flex items-center gap-1.5">
          <svg width="16" height="8" aria-hidden>
            <line x1="0" y1="4" x2="16" y2="4" stroke={SUPPORT} strokeWidth="2" />
          </svg>
          support
        </span>
        <span className="flex items-center gap-1.5">
          <svg width="16" height="8" aria-hidden>
            <line x1="0" y1="4" x2="16" y2="4" stroke={RESISTANCE} strokeWidth="2" />
          </svg>
          resistance
        </span>
        <span className="text-muted-foreground/70">solid = strong · dashed = medium · dotted = weak</span>
      </div>
    </div>
  )
}
