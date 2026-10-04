"use client"

import { useEffect, useRef, useState } from "react"
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  LineStyle,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
} from "lightweight-charts"
import { usePublicClient } from "wagmi"
import { parseAbi } from "viem"
import { ShieldCheck } from "lucide-react"

import { Button } from "@/components/ui/button"
import MarkOverlay from "@/components/mark-overlay"
import PositionOverlay from "@/components/position-overlay"
import { DEFAULT_INDICATORS, IndicatorSwitches, useIndicatorPanes } from "@/components/indicator-panes"
import type { OpenPosition } from "@/lib/positions"
import { Select, SelectContent, SelectGroup, SelectItem, SelectLabel, SelectTrigger } from "@/components/ui/select"
import type { Timeframe } from "@/lib/api"
import { formatUsd, type Ticker } from "@/lib/binance"
import type { Mark, Viewport } from "@/lib/marks"
import { STOCKS, fetchStockCandles, openVault, type Stock, type StockCandle } from "@/lib/stocks"
import { WATCHLIST } from "@/components/watchlist"

// The crypto chart's palette, so switching between the two does not change the room.
const SUPPORT = "#7af0ce"
const RESISTANCE = "#ff7a59"
const INK_MUTED = "#86948e"
const GRID = "rgba(122,240,206,0.06)"
const SURFACE = "#05100e"

const TF_SECONDS: Record<string, number> = { "1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400 }
const TIMEFRAMES: Timeframe[] = ["1m", "5m", "15m", "1h", "4h", "1d"]
const REFRESH_MS = 60_000
const ROBINHOOD_CHAIN_ID = 4663
const FEED_ABI = parseAbi([
  "function latestRoundData() view returns (uint80, int256, uint256, uint256, uint80)",
])

/**
 * A Robinhood Stock Token's chart, from its own Uniswap pool on Robinhood Chain.
 *
 * Deliberately a separate component from the crypto chart rather than a mode of it:
 * that chart is built around Binance's stream and the level and pattern analysis,
 * none of which has ever seen a stock. This one draws the pool, says where the
 * candles come from, shows the Chainlink price the vault actually trusts beside it,
 * and offers the vault - the one thing a stock can do here today.
 */
export default function StockChart({
  stock,
  quote,
  timeframe,
  onTimeframeChange,
  onSymbolChange,
  onViewportChange,
  marks = [],
  positions = [],
}: {
  stock: Stock
  quote?: Ticker
  timeframe: Timeframe
  onTimeframeChange: (tf: Timeframe) => void
  onSymbolChange: (symbol: string) => void
  /** The window on screen, in unix ms, so the assistant reads exactly these candles. */
  onViewportChange?: (viewport: Viewport | null) => void
  /** What the assistant asked to draw: levels, sweeps and other bar markers, pattern shapes. */
  marks?: Mark[]
  /** Open vault positions in this stock: entry, take-profit and stop-loss are drawn. */
  positions?: OpenPosition[]
}) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const candleRef = useRef<ISeriesApi<"Candlestick"> | null>(null)
  const volumeRef = useRef<ISeriesApi<"Histogram"> | null>(null)
  const candlesRef = useRef<StockCandle[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [last, setLast] = useState<number | null>(null)
  const [oracle, setOracle] = useState<{ price: number; ageHours: number } | null>(null)
  const [indicators, setIndicators] = useState(DEFAULT_INDICATORS)
  const [candleVersion, setCandleVersion] = useState(0)
  const client = usePublicClient({ chainId: ROBINHOOD_CHAIN_ID })
  useIndicatorPanes(chartRef.current, candlesRef.current, candleVersion, indicators, true)

  useEffect(() => {
    if (!containerRef.current) return
    const chart = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: SURFACE },
        textColor: INK_MUTED,
        fontSize: 11,
        attributionLogo: false,
      },
      grid: { vertLines: { color: GRID }, horzLines: { color: GRID } },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: INK_MUTED, width: 1, style: LineStyle.Dotted, labelBackgroundColor: "#2a2b33" },
        horzLine: { color: INK_MUTED, width: 1, style: LineStyle.Dotted, labelBackgroundColor: "#2a2b33" },
      },
      rightPriceScale: { borderColor: GRID, scaleMargins: { top: 0.08, bottom: 0.22 } },
      timeScale: { borderColor: GRID, timeVisible: true, secondsVisible: false },
      autoSize: true,
    })
    candleRef.current = chart.addSeries(CandlestickSeries, {
      upColor: "rgba(0,0,0,0)",
      downColor: RESISTANCE,
      borderUpColor: SUPPORT,
      borderDownColor: RESISTANCE,
      wickUpColor: SUPPORT,
      wickDownColor: RESISTANCE,
      priceLineColor: INK_MUTED,
      priceLineStyle: LineStyle.Dashed,
    })
    volumeRef.current = chart.addSeries(HistogramSeries, {
      priceScaleId: "volume",
      priceFormat: { type: "volume" },
      lastValueVisible: false,
      priceLineVisible: false,
    })
    chart.priceScale("volume").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } })
    chartRef.current = chart
    return () => {
      chart.remove()
      chartRef.current = null
      candleRef.current = null
      volumeRef.current = null
    }
  }, [])

  useEffect(() => {
    let alive = true
    let first = true
    const load = async () => {
      if (first) setLoading(true)
      try {
        const candles = await fetchStockCandles(stock, timeframe)
        if (!alive || !candleRef.current || !volumeRef.current) return
        candlesRef.current = candles
        setCandleVersion((v) => v + 1)
        candleRef.current.setData(
          candles.map((c) => ({ time: c.time as UTCTimestamp, open: c.open, high: c.high, low: c.low, close: c.close })),
        )
        volumeRef.current.setData(
          candles.map((c) => ({
            time: c.time as UTCTimestamp,
            value: c.volume,
            color: c.close >= c.open ? "rgba(122,240,206,0.35)" : "rgba(255,122,89,0.35)",
          })),
        )
        if (first) chartRef.current?.timeScale().fitContent()
        setLast(candles.length ? candles[candles.length - 1].close : null)
        setError(candles.length ? null : "No swaps in this pool for that window yet.")
      } catch (err) {
        if (alive) setError(err instanceof Error ? err.message : "Could not load the pool's candles")
      } finally {
        if (alive) setLoading(false)
        first = false
      }
    }
    void load()
    const id = window.setInterval(load, REFRESH_MS)
    return () => {
      alive = false
      window.clearInterval(id)
    }
  }, [stock, timeframe])

  // Report the window on screen once each pan settles, as the crypto chart does, so
  // a question about "here" is answered about these candles and no others.
  useEffect(() => {
    const chart = chartRef.current
    if (!chart || !onViewportChange) return
    let timer: ReturnType<typeof setTimeout> | null = null
    const report = () => {
      if (timer) clearTimeout(timer)
      timer = setTimeout(() => {
        const candles = candlesRef.current
        const logical = chart.timeScale().getVisibleLogicalRange()
        if (!logical || candles.length === 0) return onViewportChange(null)
        const first = Math.max(0, Math.ceil(logical.from))
        const last = Math.min(candles.length - 1, Math.floor(logical.to))
        if (first > last) return onViewportChange(null)
        onViewportChange({ from: candles[first].time * 1000, to: candles[last].time * 1000 })
      }, 250)
    }
    chart.timeScale().subscribeVisibleLogicalRangeChange(report)
    report()
    return () => {
      if (timer) clearTimeout(timer)
      chart.timeScale().unsubscribeVisibleLogicalRangeChange(report)
    }
  }, [onViewportChange, loading, stock, timeframe])

  // The price the vault prices against, and how old it is. On a weekend this is
  // Friday's close, and saying so is the point.
  useEffect(() => {
    let alive = true
    setOracle(null)
    if (!client) return
    void (async () => {
      try {
        const [, answer, , updatedAt] = (await client.readContract({
          address: stock.feed,
          abi: FEED_ABI,
          functionName: "latestRoundData",
        })) as readonly [bigint, bigint, bigint, bigint, bigint]
        if (!alive) return
        setOracle({
          price: Number(answer) / 1e8,
          ageHours: Math.max(0, (Date.now() / 1000 - Number(updatedAt)) / 3600),
        })
      } catch {
        if (alive) setOracle(null)
      }
    })()
    return () => {
      alive = false
    }
  }, [client, stock])

  const price = quote?.price ?? last
  const up = (quote?.changePct ?? 0) >= 0
  const gapPct = oracle && price ? ((price - oracle.price) / oracle.price) * 100 : null

  return (
    <div className="flex h-full w-full flex-col bg-card">
      <div className="flex flex-wrap items-center gap-2 border-b border-border px-3 py-2">
        <Select value={stock.symbol} onValueChange={onSymbolChange}>
          <SelectTrigger aria-label="Market" className="h-9 w-[150px] shrink-0 border-border bg-secondary sm:w-[200px]">
            <span className="flex min-w-0 items-center gap-2">
              <span className="font-semibold">{stock.symbol}</span>
              <span className="hidden truncate text-xs text-muted-foreground sm:inline">{stock.name}</span>
            </span>
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              <SelectLabel className="text-[10px] uppercase tracking-wide">Stocks · Robinhood Chain</SelectLabel>
              {STOCKS.map((s) => (
                <SelectItem key={s.symbol} value={s.symbol}>
                  <span className="font-semibold">{s.symbol}</span>
                  <span className="ml-2 text-xs text-muted-foreground">{s.name}</span>
                </SelectItem>
              ))}
            </SelectGroup>
            <SelectGroup>
              <SelectLabel className="text-[10px] uppercase tracking-wide">Crypto · Binance</SelectLabel>
              {WATCHLIST.map((s) => (
                <SelectItem key={s} value={s}>
                  <span className="font-semibold">{s}</span>
                </SelectItem>
              ))}
            </SelectGroup>
          </SelectContent>
        </Select>

        {price !== null && price !== undefined && (
          <span className="text-sm tabular-nums text-foreground">${formatUsd(price)}</span>
        )}
        {quote && (
          <span className="text-[11px] tabular-nums" style={{ color: up ? SUPPORT : RESISTANCE }}>
            {up ? "+" : ""}
            {quote.changePct.toFixed(2)}% 24h
          </span>
        )}

        <div className="flex gap-0.5 rounded-md bg-secondary p-0.5">
          {TIMEFRAMES.map((tf) => (
            <button
              key={tf}
              type="button"
              onClick={() => onTimeframeChange(tf)}
              className={`rounded px-2 py-1 font-mono text-[11px] ${
                timeframe === tf ? "bg-background text-primary" : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {tf}
            </button>
          ))}
        </div>

        <IndicatorSwitches value={indicators} onChange={setIndicators} />

        <Button size="sm" className="ml-auto h-8 gap-1.5 text-xs" onClick={() => openVault(stock.market)}>
          <ShieldCheck className="h-3.5 w-3.5" /> Trade {stock.symbol} in your vault
        </Button>
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-border px-3 py-1.5 text-[11px] text-muted-foreground">
        <span>
          Robinhood Stock Token · candles from its {stock.market} {stock.feePct}% Uniswap pool on Robinhood Chain
        </span>
        {oracle && (
          <span className="tabular-nums">
            Chainlink ${formatUsd(oracle.price)}
            {gapPct !== null && ` (pool ${gapPct >= 0 ? "+" : ""}${gapPct.toFixed(2)}%)`} · updated{" "}
            {oracle.ageHours < 1 ? "under an hour" : `${Math.round(oracle.ageHours)}h`} ago
            {oracle.ageHours > 6 ? " · US market closed" : ""}
          </span>
        )}
      </div>

      <div className="relative min-h-0 flex-1">
        <div ref={containerRef} className="absolute inset-0" />
        {/* The crypto chart's overlay, reused: it draws levels, bar markers such as
            sweeps, and pattern shapes, and both charts keep candle times in seconds. */}
        {marks.length > 0 && (
          <MarkOverlay chart={chartRef.current} series={candleRef.current} marks={marks} loading={loading} />
        )}
        {positions.length > 0 && !loading && (
          <PositionOverlay
            chart={chartRef.current}
            series={candleRef.current}
            positions={positions}
            timeframeSeconds={TF_SECONDS[timeframe] ?? 3600}
          />
        )}
        {(loading || error) && (
          <div className="pointer-events-none absolute inset-x-0 top-3 flex justify-center">
            <span className="rounded bg-secondary/90 px-2 py-1 text-[11px] text-muted-foreground">
              {loading ? "Loading pool candles…" : error}
            </span>
          </div>
        )}
      </div>

      <p className="border-t border-border px-3 py-1.5 text-[10px] leading-relaxed text-muted-foreground">
        Ask the assistant about this chart - it reads these pool candles. Alerts and rules run on exchange
        candles and cover the crypto pairs only; a stock is traded here through your vault, against the
        Chainlink price above.
      </p>
    </div>
  )
}
