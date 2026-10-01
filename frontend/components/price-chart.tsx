"use client"

import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  LineSeries,
  LineStyle,
  createChart,
  type IChartApi,
  type IPriceLine,
  type ISeriesApi,
  type SeriesType,
  type UTCTimestamp,
} from "lightweight-charts"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Button } from "@/components/ui/button"
import PatternOverlay from "@/components/pattern-overlay"
import {
  SOURCES,
  STRICTNESS,
  TIMEFRAMES,
  analyseLevels,
  analysePatterns,
  fetchCandles,
  formatPrice,
  patternPoints,
  type LiquidityData,
  type LiquidityLevel,
  type MsCandle,
  type Pattern,
  type PatternSource,
  type Strictness,
  type Timeframe,
} from "@/lib/api"

/*
 * Candles carry no hue - direction is hollow (up) vs filled (down), which
 * stays readable under every form of colour blindness and frees the only two
 * hues on the canvas for the levels. Blue/orange is validated against this
 * surface: CVD dE 26.8, normal-vision dE 31.8.
 */
const SUPPORT = "#3987e5"
const RESISTANCE = "#d95926"
const INK = "#c3c2b7"
const INK_MUTED = "#898781"
const GRID = "rgba(255,255,255,0.06)"
const SURFACE = "#17181e"

const CANDLE_LIMIT = 1000

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
  if (strength === "strong") return { width: 2 as const, style: LineStyle.Solid }
  if (strength === "medium") return { width: 2 as const, style: LineStyle.Dashed }
  return { width: 1 as const, style: LineStyle.Dotted }
}

interface MarkedLevel extends LiquidityLevel {
  kind: "support" | "resistance"
}

type ChartStyle = "candle" | "line"

/** A candlestick series wants OHLC; a line series wants a single value. */
function applyCandles(
  series: ISeriesApi<SeriesType>,
  candles: MsCandle[],
  style: ChartStyle,
) {
  const data =
    style === "candle"
      ? candles.map((c) => ({
          time: (c.time / 1000) as UTCTimestamp,
          open: c.open,
          high: c.high,
          low: c.low,
          close: c.close,
        }))
      : candles.map((c) => ({
          time: (c.time / 1000) as UTCTimestamp,
          value: c.close,
        }))
  series.setData(data as never)
}

interface PriceChartProps {
  symbol?: string
  onSymbolChange?: (symbol: string) => void
  /** Levels pushed from chat via "Mark on Chart". */
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
  const [timeframe, setTimeframe] = useState<Timeframe>("1h")

  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [live, setLive] = useState(false)
  const [spot, setSpot] = useState<number | undefined>()
  const [levels, setLevels] = useState<MarkedLevel[]>([])
  const [autoLevels, setAutoLevels] = useState(false)
  const [analysing, setAnalysing] = useState(false)

  const [chartStyle, setChartStyle] = useState<"candle" | "line">("candle")
  const [showPatterns, setShowPatterns] = useState(false)
  const [strictness, setStrictness] = useState<Strictness>("balanced")
  const [source, setSource] = useState<PatternSource>("wick")
  const [patterns, setPatterns] = useState<Pattern[]>([])
  const [patternTotal, setPatternTotal] = useState(0)

  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const seriesRef = useRef<ISeriesApi<SeriesType> | null>(null)
  // Kept so the visible logical range can be mapped back to real timestamps.
  const candlesRef = useRef<MsCandle[]>([])
  const priceLinesRef = useRef<IPriceLine[]>([])
  const rangeTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const analysisAbort = useRef<AbortController | null>(null)
  const patternTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const patternAbort = useRef<AbortController | null>(null)

  /* ---------------------------------------------------------------- chart */

  useEffect(() => {
    if (!containerRef.current) return

    const chart = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: SURFACE },
        textColor: INK_MUTED,
        fontSize: 11,
        attributionLogo: false,
      },
      grid: {
        vertLines: { color: GRID },
        horzLines: { color: GRID },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: INK_MUTED, width: 1, style: LineStyle.Dotted, labelBackgroundColor: "#2a2b33" },
        horzLine: { color: INK_MUTED, width: 1, style: LineStyle.Dotted, labelBackgroundColor: "#2a2b33" },
      },
      rightPriceScale: { borderColor: GRID },
      timeScale: { borderColor: GRID, timeVisible: true, secondsVisible: false },
      autoSize: true,
    })

    chartRef.current = chart

    return () => {
      chart.remove()
      chartRef.current = null
      seriesRef.current = null
      priceLinesRef.current = []
    }
  }, [])

  /*
   * The series is separate from the chart so switching between candles and a
   * line does not tear down the view. Data already fetched is re-applied
   * straight away, so the swap costs no request and keeps the same window.
   */
  useEffect(() => {
    const chart = chartRef.current
    if (!chart) return

    const series =
      chartStyle === "candle"
        ? chart.addSeries(CandlestickSeries, {
            // Hollow up, filled down.
            upColor: "rgba(0,0,0,0)",
            downColor: INK,
            borderUpColor: INK,
            borderDownColor: INK,
            wickUpColor: INK,
            wickDownColor: INK,
            priceLineVisible: true,
            priceLineColor: INK_MUTED,
            priceLineStyle: LineStyle.Dashed,
          })
        : chart.addSeries(LineSeries, {
            color: INK,
            lineWidth: 2,
            priceLineVisible: true,
            priceLineColor: INK_MUTED,
            priceLineStyle: LineStyle.Dashed,
          })

    seriesRef.current = series
    priceLinesRef.current = [] // belonged to the series just replaced
    if (candlesRef.current.length) applyCandles(series, candlesRef.current, chartStyle)

    return () => {
      chart.removeSeries(series)
      if (seriesRef.current === series) seriesRef.current = null
    }
  }, [chartStyle])

  /*
   * Keep the price source in step with what is actually drawn.
   *
   * A line chart plots closes, so detecting on wicks there marks shoulders at
   * prices the line never shows and the dots float off the curve. Switching
   * view therefore switches source to match; the source toggle stays live
   * afterwards, so an intentional mismatch is still one click away.
   */
  useEffect(() => {
    setSource(chartStyle === "line" ? "close" : "wick")
  }, [chartStyle])

  /* --------------------------------------------------------------- history */

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setError(null)

    fetchCandles(selected, timeframe, CANDLE_LIMIT, controller.signal)
      .then((candles) => {
        if (controller.signal.aborted || !seriesRef.current) return
        candlesRef.current = candles
        applyCandles(seriesRef.current, candles, chartStyle)
        chartRef.current?.timeScale().fitContent()
        setSpot(candles.at(-1)?.close)
        setLoading(false)
      })
      .catch((e) => {
        if (controller.signal.aborted) return
        setError(e?.message ?? "Could not load chart data")
        setLoading(false)
      })

    return () => controller.abort()
  }, [selected, timeframe])

  /* ------------------------------------------------------------ live ticks */

  useEffect(() => {
    if (loading || error) return

    let socket: WebSocket | null = null
    let retry: ReturnType<typeof setTimeout> | undefined
    let attempts = 0
    let disposed = false

    const connect = () => {
      if (disposed) return
      socket = new WebSocket(
        `wss://stream.binance.com:9443/ws/${selected.toLowerCase()}@kline_${timeframe}`,
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
        if (!k || !seriesRef.current) return

        // update() replaces the bar at this time, or appends a new one.
        const time = (k.t / 1000) as UTCTimestamp
        seriesRef.current.update(
          (chartStyle === "candle"
            ? {
                time,
                open: Number(k.o),
                high: Number(k.h),
                low: Number(k.l),
                close: Number(k.c),
              }
            : { time, value: Number(k.c) }) as never,
        )
        setSpot(Number(k.c))
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
  }, [selected, timeframe, loading, error, chartStyle])

  /* ------------------------------------------------- viewport -> analysis */

  /**
   * The timestamps bounding what is currently on screen.
   *
   * getVisibleRange() returns null whenever the view extends past the data,
   * which is most of the time after fitContent(). The logical range is always
   * available, so take indices and map them onto our own candle timestamps.
   */
  const visibleWindow = useCallback((): { from: number; to: number } | null => {
    const chart = chartRef.current
    const candles = candlesRef.current
    if (!chart || candles.length === 0) return null

    const logical = chart.timeScale().getVisibleLogicalRange()
    if (!logical) return null

    const firstIndex = Math.max(0, Math.ceil(logical.from))
    const lastIndex = Math.min(candles.length - 1, Math.floor(logical.to))
    if (firstIndex > lastIndex) return null // scrolled entirely off the data

    return { from: candles[firstIndex].time, to: candles[lastIndex].time }
  }, [])

  const analyseVisible = useCallback(async () => {
    const window = visibleWindow()
    if (!window) {
      setLevels([])
      return
    }

    analysisAbort.current?.abort()
    const controller = new AbortController()
    analysisAbort.current = controller
    setAnalysing(true)

    try {
      const data = await analyseLevels(
        { symbol: selected, timeframe, from: window.from, to: window.to },
        controller.signal,
      )
      if (controller.signal.aborted) return
      setLevels([
        ...(data.support_levels ?? []).map((l) => ({ ...l, kind: "support" as const })),
        ...(data.resistance_levels ?? []).map((l) => ({ ...l, kind: "resistance" as const })),
      ])
    } catch (e: any) {
      if (e?.name !== "AbortError") setError(e?.message ?? "Analysis failed")
    } finally {
      // Only the newest request owns the spinner; a superseded one leaving it
      // on would strand the button reading "Analysing..." forever.
      if (analysisAbort.current === controller) setAnalysing(false)
    }
  }, [selected, timeframe, visibleWindow])

  const detectPatterns = useCallback(async () => {
    const window = visibleWindow()
    if (!window) {
      setPatterns([])
      setPatternTotal(0)
      return
    }

    patternAbort.current?.abort()
    const controller = new AbortController()
    patternAbort.current = controller

    try {
      const data = await analysePatterns(
        {
          symbol: selected,
          timeframe,
          from: window.from,
          to: window.to,
          strictness,
          source,
        },
        controller.signal,
      )
      if (controller.signal.aborted) return
      setPatterns(data.patterns ?? [])
      setPatternTotal(data.total_found ?? 0)
    } catch (e: any) {
      // Keep the last drawing rather than blanking the chart mid-pan.
      if (e?.name !== "AbortError") setError(e?.message ?? "Pattern detection failed")
    }
  }, [selected, timeframe, strictness, source, visibleWindow])

  // Re-analyse as the view moves, but only once the pan settles.
  useEffect(() => {
    const chart = chartRef.current
    if (!chart || !autoLevels) return

    const onRangeChange = () => {
      if (rangeTimer.current) clearTimeout(rangeTimer.current)
      rangeTimer.current = setTimeout(analyseVisible, 250)
    }

    chart.timeScale().subscribeVisibleLogicalRangeChange(onRangeChange)
    onRangeChange()

    return () => {
      chart.timeScale().unsubscribeVisibleLogicalRangeChange(onRangeChange)
      if (rangeTimer.current) clearTimeout(rangeTimer.current)
      analysisAbort.current?.abort()
    }
  }, [autoLevels, analyseVisible])

  // Patterns follow the view the same way levels do.
  useEffect(() => {
    const chart = chartRef.current
    if (!chart || !showPatterns) return

    const onRangeChange = () => {
      if (patternTimer.current) clearTimeout(patternTimer.current)
      patternTimer.current = setTimeout(detectPatterns, 250)
    }

    chart.timeScale().subscribeVisibleLogicalRangeChange(onRangeChange)
    onRangeChange()

    return () => {
      chart.timeScale().unsubscribeVisibleLogicalRangeChange(onRangeChange)
      if (patternTimer.current) clearTimeout(patternTimer.current)
      patternAbort.current?.abort()
    }
  }, [showPatterns, detectPatterns])

  // Levels pushed from chat replace whatever is on the chart.
  useEffect(() => {
    if (!liquidityData || liquidityData.symbol !== selected) return
    const { support_levels = [], resistance_levels = [] } = liquidityData.liquidityData
    setAutoLevels(false)
    setLevels([
      ...support_levels.map((l) => ({ ...l, kind: "support" as const })),
      ...resistance_levels.map((l) => ({ ...l, kind: "resistance" as const })),
    ])
  }, [liquidityData, selected])

  // Clear drawings when the underlying series changes out from under them.
  useEffect(() => {
    setLevels([])
    setPatterns([])
    setPatternTotal(0)
  }, [selected, timeframe])

  /* -------------------------------------------------------- draw the lines */

  useEffect(() => {
    const series = seriesRef.current
    if (!series) return

    for (const line of priceLinesRef.current) series.removePriceLine(line)
    priceLinesRef.current = levels.map((level) => {
      const { width, style } = strengthStyle(level.strength)
      return series.createPriceLine({
        price: level.price,
        color: level.kind === "support" ? SUPPORT : RESISTANCE,
        lineWidth: width,
        lineStyle: style,
        axisLabelVisible: true,
        title: `${level.kind === "support" ? "S" : "R"} ${level.strength}`,
      })
    })
  }, [levels])

  const railLevels = useMemo(() => [...levels].sort((a, b) => b.price - a.price), [levels])

  return (
    <div className="flex h-full w-full flex-col bg-card">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-4 py-3">
        <div className="flex items-center gap-3">
          <Select value={selected} onValueChange={(v) => onSymbolChange?.(v)}>
            <SelectTrigger className="w-[210px] border-border bg-secondary">
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

        <div className="flex items-center gap-2">
          {/* Timeframes */}
          <div className="flex overflow-hidden rounded-md border border-border">
            {TIMEFRAMES.map((tf) => (
              <button
                key={tf}
                onClick={() => setTimeframe(tf)}
                aria-pressed={tf === timeframe}
                className={`px-2.5 py-1 font-mono text-xs transition-colors ${
                  tf === timeframe
                    ? "bg-secondary text-foreground"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                {tf}
              </button>
            ))}
          </div>

          {/* Candles or line. A line is the shape the detector reads when the
              source below is set to closes. */}
          <div className="flex overflow-hidden rounded-md border border-border">
            {(["candle", "line"] as const).map((style) => (
              <button
                key={style}
                onClick={() => setChartStyle(style)}
                aria-pressed={style === chartStyle}
                title={
                  style === "candle"
                    ? "Candles, with wick detail"
                    : "Closing prices only, less noise"
                }
                className={`px-2 py-1 text-xs capitalize transition-colors ${
                  style === chartStyle
                    ? "bg-secondary text-foreground"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                {style}
              </button>
            ))}
          </div>

          <Button
            variant={autoLevels ? "secondary" : "ghost"}
            size="sm"
            className="h-7 text-xs"
            onClick={() => {
              if (autoLevels) {
                setAutoLevels(false)
                setLevels([])
              } else {
                setAutoLevels(true)
              }
            }}
          >
            {analysing ? "Analysing…" : autoLevels ? "Levels: on" : "Levels: off"}
          </Button>

          <Button
            variant={showPatterns ? "secondary" : "ghost"}
            size="sm"
            className="h-7 text-xs"
            onClick={() => {
              if (showPatterns) {
                setShowPatterns(false)
                setPatterns([])
                setPatternTotal(0)
              } else {
                setShowPatterns(true)
              }
            }}
          >
            {showPatterns ? "Patterns: on" : "Patterns: off"}
          </Button>

          {showPatterns && (
            <div className="flex overflow-hidden rounded-md border border-border">
              {SOURCES.map((src) => (
                <button
                  key={src}
                  onClick={() => setSource(src)}
                  aria-pressed={src === source}
                  title={
                    src === "wick"
                      ? "Measure patterns on highs and lows, the classic definition"
                      : "Measure on closing prices, ignoring wick spikes and stop hunts"
                  }
                  className={`px-2 py-1 text-xs capitalize transition-colors ${
                    src === source
                      ? "bg-secondary text-foreground"
                      : "text-muted-foreground hover:text-foreground"
                  }`}
                >
                  {src}
                </button>
              ))}
            </div>
          )}

          {showPatterns && (
            <div className="flex overflow-hidden rounded-md border border-border">
              {STRICTNESS.map((s) => (
                <button
                  key={s}
                  onClick={() => setStrictness(s)}
                  aria-pressed={s === strictness}
                  title={
                    s === "strict"
                      ? "Only unambiguous patterns"
                      : s === "loose"
                        ? "Catches rough and asymmetric shapes too"
                        : "Textbook patterns, shallow wobbles ignored"
                  }
                  className={`px-2 py-1 text-xs capitalize transition-colors ${
                    s === strictness
                      ? "bg-secondary text-foreground"
                      : "text-muted-foreground hover:text-foreground"
                  }`}
                >
                  {s}
                </button>
              ))}
            </div>
          )}

          {levels.length > 0 && !autoLevels && (
            <Button
              variant="ghost"
              size="sm"
              className="h-7 text-xs"
              onClick={() => {
                setLevels([])
                onClearLevels?.()
              }}
            >
              Clear
            </Button>
          )}
        </div>
      </div>

      <div className="flex min-h-0 flex-1">
        {/* Chart */}
        <div className="relative min-w-0 flex-1">
          <div ref={containerRef} className="absolute inset-0" />
          {showPatterns && (
            <PatternOverlay
              chart={chartRef.current}
              series={seriesRef.current}
              patterns={patterns}
            />
          )}
          {loading && (
            <div className="pointer-events-none absolute inset-0 grid place-items-center text-sm text-muted-foreground">
              Loading {selected} {timeframe}…
            </div>
          )}
          {error && (
            <div className="absolute inset-x-0 top-2 mx-auto w-fit rounded-md border border-border bg-card/95 px-3 py-1.5 text-xs text-muted-foreground">
              {error}
            </div>
          )}
        </div>

        {/* Level rail */}
        <div className="w-[190px] shrink-0 overflow-y-auto border-l border-border px-3 py-3">
          {showPatterns && (
            <div className="mb-4">
              <div className="mb-2 flex items-baseline justify-between">
                <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                  Patterns
                </span>
                {patternTotal > patterns.length && (
                  <span
                    className="text-[10px] text-muted-foreground/70"
                    title={`${patternTotal} found in view, showing the ${patterns.length} most actionable`}
                  >
                    {patterns.length}/{patternTotal}
                  </span>
                )}
              </div>

              {patterns.length === 0 ? (
                <p className="text-xs leading-relaxed text-muted-foreground">
                  None in view. Try a looser setting, or pan to more price action.
                </p>
              ) : (
                <ul className="space-y-2">
                  {patterns.map((p, i) => {
                    const colour = p.kind === "W" ? SUPPORT : RESISTANCE
                    const pts = patternPoints(p)
                    return (
                      <li key={`${p.kind}-${pts[0].time}-${i}`} className="text-xs">
                        <div className="flex items-center gap-1.5">
                          <span className="font-semibold" style={{ color: colour }}>
                            {p.kind}
                          </span>
                          <span className="text-foreground">{p.state}</span>
                          <span className="ml-auto tabular-nums text-muted-foreground">
                            {Math.round(p.confidence)}%
                          </span>
                        </div>
                        <div className="text-[11px] text-muted-foreground">
                          neck ${formatPrice(p.neckline)}
                          {p.state === "confirmed" && ` → $${formatPrice(p.target)}`}
                        </div>
                      </li>
                    )
                  })}
                </ul>
              )}
            </div>
          )}

          <div className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            Liquidity levels
          </div>

          {railLevels.length === 0 ? (
            <p className="text-xs leading-relaxed text-muted-foreground">
              Turn <span className="text-foreground">Levels</span> on to analyse the visible
              range, or ask the assistant and press{" "}
              <span className="text-foreground">Mark on chart</span>.
            </p>
          ) : (
            <ul className="space-y-1.5">
              {railLevels.map((level, i) => {
                const colour = level.kind === "support" ? SUPPORT : RESISTANCE
                const dash =
                  level.strength === "strong" ? undefined : level.strength === "medium" ? "7 4" : "2 4"
                return (
                  <li key={`${level.kind}-${level.price}-${i}`} className="flex items-start gap-2">
                    <svg width="14" height="10" className="mt-1 shrink-0" aria-hidden>
                      <line
                        x1="0"
                        y1="5"
                        x2="14"
                        y2="5"
                        stroke={colour}
                        strokeWidth={level.strength === "weak" ? 1 : 2}
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
        {chartStyle === "candle" && (
          <>
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
          </>
        )}

        {showPatterns && (
          <span className="flex items-center gap-1.5">
            <svg width="18" height="9" aria-hidden>
              <polyline
                points="1,1 5,7 9,3 13,7 17,1"
                fill="none"
                stroke={SUPPORT}
                strokeWidth="1.5"
              />
            </svg>
            W / M {source === "wick" ? "(on wicks)" : "(on closes)"}
          </span>
        )}
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
        <span className="text-muted-foreground/70">
          solid = strong · dashed = medium · dotted = weak · scroll to zoom, drag to pan
        </span>
      </div>
    </div>
  )
}
