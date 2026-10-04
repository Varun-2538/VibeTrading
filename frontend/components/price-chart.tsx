"use client"

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react"
import { createPortal } from "react-dom"
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
import { Select, SelectContent, SelectItem, SelectTrigger } from "@/components/ui/select"
import { Button } from "@/components/ui/button"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import { Layers, ShieldCheck, SlidersHorizontal, Sparkles } from "lucide-react"
import MarkOverlay from "@/components/mark-overlay"
import PositionOverlay from "@/components/position-overlay"
import { IndicatorBar, useChartIndicators, useIndicatorPanes } from "@/components/indicator-panes"
import type { OpenPosition } from "@/lib/positions"
import { STOCKS, openVault } from "@/lib/stocks"
import PatternOverlay from "@/components/pattern-overlay"
import type { Mark, PatternSettings, Viewport } from "@/lib/marks"
import {
  PATTERN_SCALES,
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
  type PatternScale,
  type PatternSource,
  type Strictness,
  type Timeframe,
} from "@/lib/api"

/*
 * Brand mint for support and up, coral for resistance and down. Direction is
 * still hollow (up) vs filled (down), so it never rests on hue alone.
 *
 * The coral is deliberately deeper than the design's salmon (#ffb4ab): mint
 * against salmon collapses to dE 15.9 under deuteranopia and 13.4 under
 * protanopia, where #ff7a59 holds 46.1 and 37.1 (normal vision 98.7).
 */
const SUPPORT = "#7af0ce"
const RESISTANCE = "#ff7a59"
const INK = "#d8e5e1"
const INK_MUTED = "#86948e"
const GRID = "rgba(122,240,206,0.06)"
const SURFACE = "#05100e"

const CANDLE_LIMIT = 1000
const TF_SECONDS: Record<string, number> = { "1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400 }

/**
 * ETH as Robinhood Chain trades it: the WETH/USDG pool. The candles, the rules and
 * the assistant still read ETH's price from Binance - USDG and USDT are both
 * dollars - so only the label, and the vault a trade lands in, differ.
 */
export const ROBINHOOD_ETH = "ETHUSDG"

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

const CHART_STYLES = ["candle", "line"] as const
type ChartStyle = (typeof CHART_STYLES)[number]

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
  /** Controlled by the page so the strategy panel can read the same timeframe. */
  timeframe: Timeframe
  onTimeframeChange: (timeframe: Timeframe) => void
  /** Levels pushed from chat via "Mark on Chart". */
  liquidityData?: { symbol: string; liquidityData: LiquidityData } | null
  onClearLevels?: () => void
  /**
   * The on-screen window and the detector settings, reported upward so the
   * chat can ask about exactly what is drawn. Null while nothing is on screen.
   */
  onViewportChange?: (viewport: Viewport | null) => void
  onPatternSettingsChange?: (settings: PatternSettings) => void
  /** What the chat fellow asked to draw. Already checked against the detectors. */
  marks?: Mark[]
  onClearMarks?: () => void
  /**
   * Desktop-only mount points elsewhere on the page. When given, the toolbar,
   * the pattern settings and the level rail render there through portals
   * instead of inside the chart card. State stays here either way, and the
   * compact layout never uses them.
   */
  slots?: PanelSlots
  /** 24h change and quote volume for the selected pair, from the ticker feed. */
  changePct?: number
  quoteVolume?: number
  /** Show ETH as Robinhood Chain's ETH/USDG; the data is ETH's either way. */
  robinhood?: boolean
  /**
   * A stock covering this chart. The top bar stays this one - same symbol list,
   * price and timeframes - and only drops the controls that read Binance.
   */
  stockView?: { symbol: string; name: string; price?: number; changePct?: number }
  /** Open vault positions on this pair: entry, take-profit and stop-loss are drawn. */
  positions?: OpenPosition[]
}

export interface PanelSlots {
  toolbar?: HTMLElement | null
  detection?: HTMLElement | null
  rail?: HTMLElement | null
}

interface Ohlc {
  open: number
  high: number
  low: number
  close: number
}

export default function PriceChart({
  symbol,
  onSymbolChange,
  timeframe,
  onTimeframeChange,
  liquidityData,
  onClearLevels,
  onViewportChange,
  onPatternSettingsChange,
  marks = [],
  onClearMarks,
  slots,
  changePct,
  quoteVolume,
  robinhood = false,
  stockView,
  positions = [],
}: PriceChartProps) {
  const selected = symbol || "BTCUSDT"
  const onRobinhood = robinhood && selected === "ETHUSDT"
  const shownSymbol = onRobinhood ? ROBINHOOD_ETH : selected
  const shownLabel = onRobinhood ? "ETH/USDG" : selected
  const setTimeframe = onTimeframeChange

  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [live, setLive] = useState(false)
  const [spot, setSpot] = useState<number | undefined>()
  const [levels, setLevels] = useState<MarkedLevel[]>([])
  const [autoLevels, setAutoLevels] = useState(false)
  const [analysing, setAnalysing] = useState(false)

  const [chartStyle, setChartStyle] = useState<ChartStyle>("candle")
  const [showPatterns, setShowPatterns] = useState(false)
  const [strictness, setStrictness] = useState<Strictness>("balanced")
  const [source, setSource] = useState<PatternSource>("wick")
  const [scale, setScale] = useState<PatternScale>("swing")
  const [patterns, setPatterns] = useState<Pattern[]>([])
  const [patternTotal, setPatternTotal] = useState(0)
  // The candle under the crosshair, or the latest one when nothing is hovered.
  const [hovered, setHovered] = useState<Ohlc | null>(null)
  const [indicators, setIndicators] = useChartIndicators()
  // Bumped whenever candlesRef changes, history or a live tick, so the indicator
  // panes recompute from the same bars the price pane draws.
  const [candleVersion, setCandleVersion] = useState(0)
  const [latest, setLatest] = useState<Ohlc | null>(null)

  /*
   * Below the desktop breakpoint the toolbar's controls and the level rail
   * have nowhere to sit beside a chart that needs the whole screen, so each
   * gets a sheet. Both are closed at every width above it, where the same
   * content is rendered inline instead.
   */
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [railOpen, setRailOpen] = useState(false)

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
  const viewportTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

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
            downColor: RESISTANCE,
            borderUpColor: SUPPORT,
            borderDownColor: RESISTANCE,
            wickUpColor: SUPPORT,
            wickDownColor: RESISTANCE,
            priceLineVisible: true,
            priceLineColor: INK_MUTED,
            priceLineStyle: LineStyle.Dashed,
          })
        : chart.addSeries(LineSeries, {
            color: SUPPORT,
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
        setCandleVersion((v) => v + 1)
        applyCandles(seriesRef.current, candles, chartStyle)
        chartRef.current?.timeScale().fitContent()
        setSpot(candles.at(-1)?.close)
        setLatest(candles.at(-1) ?? null)
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
      // Held locally as well as on `socket`: by the time this connection's
      // handlers fire, `socket` may already point at a replacement.
      const ws = new WebSocket(
        `wss://stream.binance.com:9443/ws/${selected.toLowerCase()}@kline_${timeframe}`,
      )
      socket = ws

      ws.onopen = () => {
        attempts = 0
        setLive(true)
      }

      ws.onmessage = (event) => {
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
        const bars = candlesRef.current
        const tick = { time: k.t as number, open: Number(k.o), high: Number(k.h), low: Number(k.l), close: Number(k.c), volume: Number(k.v) }
        if (bars.length && bars[bars.length - 1].time === tick.time) bars[bars.length - 1] = { ...bars[bars.length - 1], ...tick }
        else if (!bars.length || bars[bars.length - 1].time < tick.time) bars.push(tick as MsCandle)
        setCandleVersion((v) => v + 1)
        setSpot(Number(k.c))
        setLatest({ open: Number(k.o), high: Number(k.h), low: Number(k.l), close: Number(k.c) })
      }

      // Close this socket, not whichever one `socket` currently holds.
      ws.onerror = () => ws.close()
      ws.onclose = () => {
        // A superseded socket must not report the live state. Its close event
        // can arrive after the replacement is already streaming, which showed
        // "offline" in the header while prices kept ticking.
        if (disposed || socket !== ws) return
        setLive(false)
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

  /* ------------------------------------------------------------ crosshair */

  useEffect(() => {
    const chart = chartRef.current
    if (!chart) return
    const onMove = (param: Parameters<Parameters<IChartApi["subscribeCrosshairMove"]>[0]>[0]) => {
      const series = seriesRef.current
      const bar = series && param.time ? (param.seriesData.get(series) as Partial<Ohlc> | undefined) : undefined
      setHovered(
        bar && bar.open !== undefined && bar.high !== undefined && bar.low !== undefined && bar.close !== undefined
          ? { open: bar.open, high: bar.high, low: bar.low, close: bar.close }
          : null,
      )
    }
    chart.subscribeCrosshairMove(onMove)
    return () => chart.unsubscribeCrosshairMove(onMove)
  }, [])

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
          scale,
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
  }, [selected, timeframe, strictness, source, scale, visibleWindow])

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

  // Report the window on screen upward, once each pan settles. Gated on the
  // data having loaded so the first report is a real window, not null.
  useEffect(() => {
    const chart = chartRef.current
    if (!chart || loading || error || !onViewportChange) return

    const onRangeChange = () => {
      if (viewportTimer.current) clearTimeout(viewportTimer.current)
      viewportTimer.current = setTimeout(() => onViewportChange(visibleWindow()), 250)
    }

    chart.timeScale().subscribeVisibleLogicalRangeChange(onRangeChange)
    onRangeChange()

    return () => {
      chart.timeScale().unsubscribeVisibleLogicalRangeChange(onRangeChange)
      if (viewportTimer.current) clearTimeout(viewportTimer.current)
    }
  }, [loading, error, selected, timeframe, onViewportChange, visibleWindow])

  useEffect(() => {
    onPatternSettingsChange?.({ strictness, source, scale })
  }, [strictness, source, scale, onPatternSettingsChange])

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
  // Assistant and backtest marks belong to the page, which clears the ones
  // that no longer apply; clearing them here would also wipe trades a report
  // just switched the chart to show.
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

  /*
   * The toolbar's control groups are declared once and rendered twice: in a
   * row beside the chart at desktop width, and as labelled rows inside the
   * settings sheet below it. Descriptors rather than a duplicated block, so
   * the two renderings cannot drift apart.
   */
  useIndicatorPanes(chartRef.current, candlesRef.current, candleVersion, indicators)

  const controlGroups: { key: string; label: string; node: ReactNode; detection?: boolean }[] = [
    {
      key: "style",
      label: "Draw as",
      node: (
        <Segmented
          ariaLabel="Chart style"
          options={CHART_STYLES}
          value={chartStyle}
          onChange={setChartStyle}
          title={(s) =>
            s === "candle" ? "Candles, with wick detail" : "Closing prices only, less noise"
          }
        />
      ),
    },
    {
      key: "levels",
      label: "Liquidity levels",
      node: (
        <Button
          variant={autoLevels ? "secondary" : "ghost"}
          size="sm"
          className="h-9 shrink-0 text-xs lg:h-7"
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
      ),
    },
    {
      key: "patterns",
      label: "W / M patterns",
      node: (
        <Button
          variant={showPatterns ? "secondary" : "ghost"}
          size="sm"
          className="h-9 shrink-0 text-xs lg:h-7"
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
      ),
    },
  ]

  // Scale is what size of structure to hunt for; strictness is the quality bar
  // within it. Two separate questions, and neither is asked unless patterns are
  // being drawn at all.
  if (showPatterns) {
    controlGroups.push(
      {
        key: "scale",
        label: "Pattern size",
        detection: true,
        node: (
          <Segmented
            ariaLabel="Pattern scale"
            options={PATTERN_SCALES}
            value={scale}
            onChange={setScale}
            title={(s) =>
              s === "swing"
                ? "Multi-bar swing patterns only"
                : s === "scalp"
                  ? "Tight patterns inside a range — more of them, and more chop"
                  : "Both sizes at once"
            }
          />
        ),
      },
      {
        key: "source",
        label: "Measured on",
        detection: true,
        node: (
          <Segmented
            ariaLabel="Price source"
            options={SOURCES}
            value={source}
            onChange={setSource}
            title={(src) =>
              src === "wick"
                ? "Measure patterns on highs and lows, the classic definition"
                : "Measure on closing prices, ignoring wick spikes and stop hunts"
            }
          />
        ),
      },
      {
        key: "strictness",
        label: "Strictness",
        detection: true,
        node: (
          <Segmented
            ariaLabel="Strictness"
            options={STRICTNESS}
            value={strictness}
            onChange={setStrictness}
            title={(s) =>
              s === "strict"
                ? "Only unambiguous patterns"
                : s === "loose"
                  ? "Catches rough and asymmetric shapes too"
                  : "Textbook patterns, shallow wobbles ignored"
            }
          />
        ),
      },
    )
  }

  if (levels.length > 0 && !autoLevels) {
    controlGroups.push({
      key: "clear",
      label: "Marked levels",
      node: (
        <Button
          variant="ghost"
          size="sm"
          className="h-9 shrink-0 text-xs lg:h-7"
          onClick={() => {
            setLevels([])
            onClearLevels?.()
          }}
        >
          Clear
        </Button>
      ),
    })
  }

  if (marks.length > 0) {
    controlGroups.push({
      key: "clear-marks",
      label: "Assistant marks",
      node: (
        <Button
          variant="ghost"
          size="sm"
          className="h-9 shrink-0 text-xs lg:h-7"
          onClick={() => onClearMarks?.()}
        >
          Clear
        </Button>
      ),
    })
  }

  const timeframeControl = (
    <Segmented
      ariaLabel="Timeframe"
      options={TIMEFRAMES}
      value={timeframe}
      onChange={setTimeframe}
      mono
    />
  )

  /* The rail's contents, beside the chart at desktop width and in a sheet
     below it. */
  const railContent = (
    <>
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
    </>
  )

  /* The desktop top bar, when the page gives it a slot: identity, price and
     every chart control except the pattern settings, which have a card. */
  const pairName = onRobinhood ? "Robinhood Chain" : CRYPTO_PAIRS.find((c) => c.symbol === selected)?.name
  const barPrice = stockView ? stockView.price : spot
  const barChange = stockView ? stockView.changePct : changePct
  const desktopToolbar = (
    <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <Select value={stockView?.symbol ?? shownSymbol} onValueChange={(v) => onSymbolChange?.(v)}>
          <SelectTrigger aria-label="Market" className="h-10 w-[200px] border-border bg-secondary">
            <span className="flex min-w-0 items-baseline gap-2">
              <span className="text-lg font-semibold tracking-tight">{stockView?.symbol ?? shownLabel}</span>
              <span className="truncate text-xs text-muted-foreground">{stockView?.name ?? pairName}</span>
            </span>
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
            <SelectItem value={ROBINHOOD_ETH}>
              <div className="flex w-full items-center justify-between">
                <span className="font-semibold">ETH/USDG</span>
                <span className="ml-2 text-xs text-muted-foreground">Ethereum · Robinhood Chain</span>
              </div>
            </SelectItem>
            {STOCKS.map((st) => (
              <SelectItem key={st.symbol} value={st.symbol}>
                <div className="flex w-full items-center justify-between">
                  <span className="font-semibold">{st.symbol}</span>
                  <span className="ml-2 text-xs text-muted-foreground">{st.name} · stock</span>
                </div>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <div className="flex items-baseline gap-2 font-mono">
          {barPrice !== undefined && (
            <span className="text-xl font-semibold tabular-nums tracking-tight text-primary">
              ${formatPrice(barPrice)}
            </span>
          )}
          <span
            className="inline-flex items-center gap-1.5 rounded bg-muted px-1.5 py-0.5 text-[11px]"
            title={stockView ? "From the stock's pool on Robinhood Chain" : live ? "Streaming live from Binance" : "Not connected to the live feed"}
          >
            <span
              className={`inline-block h-1.5 w-1.5 rounded-full ${stockView || live ? "bg-primary" : "bg-muted-foreground/40"} ${!stockView && live ? "animate-pulse" : ""}`}
            />
            {barChange !== undefined && (
              <span style={{ color: barChange >= 0 ? SUPPORT : RESISTANCE }}>
                {barChange >= 0 ? "+" : ""}
                {barChange.toFixed(2)}%
              </span>
            )}
            <span className="text-muted-foreground">{stockView ? "24h" : live ? "live" : "offline"}</span>
          </span>
          {!stockView && quoteVolume ? (
            <span className="hidden text-[11px] text-muted-foreground xl:inline">
              24h vol <span className="text-foreground">{compactUsd(quoteVolume)} USDT</span>
            </span>
          ) : null}
        </div>

        {timeframeControl}
      </div>

      <div className={`flex flex-wrap items-center gap-2 ${stockView ? "hidden" : ""}`}>
        {controlGroups
          .filter((g) => !(slots?.detection && g.detection))
          .map((g) => (
            <div key={g.key} className="contents">
              {g.node}
            </div>
          ))}
      </div>
    </div>
  )

  /* Pattern settings, as a card of their own at desktop width. */
  const detectionContent = showPatterns ? (
    <div className="flex flex-col gap-3">
      {controlGroups
        .filter((g) => g.detection)
        .map((g) => (
          <div key={g.key} className="flex flex-col gap-1.5">
            <span className="text-[11px] text-muted-foreground">{g.label}</span>
            {g.node}
          </div>
        ))}
    </div>
  ) : (
    <div className="flex flex-col items-start gap-2">
      <p className="text-xs leading-relaxed text-muted-foreground">
        Pattern size, price source and strictness apply once W / M detection is on.
      </p>
      <Button variant="secondary" size="sm" className="h-7 text-xs" onClick={() => setShowPatterns(true)}>
        Turn patterns on
      </Button>
    </div>
  )

  // What the compact toolbar's rail button has to report.
  const railCount = railLevels.length + (showPatterns ? patterns.length : 0)

  return (
    <div className="flex h-full w-full flex-col bg-card">
      {/*
        Header. One wrapping row at desktop width; below it the identity and
        the timeframes take a row each and everything else moves to a sheet,
        because eight control groups will not sit beside each other on a phone.
      */}
      <div
        className={`flex flex-col gap-2 border-b border-border px-3 py-2 sm:flex-row sm:flex-wrap sm:items-center sm:gap-3 lg:justify-between lg:px-4 lg:py-3 ${
          slots?.toolbar ? "lg:hidden" : ""
        }`}
      >
        <div className="flex min-w-0 items-center gap-2 lg:gap-3">
          <Select value={shownSymbol} onValueChange={(v) => onSymbolChange?.(v)}>
            {/* The trigger is written out rather than left to SelectValue, so
                the coin name can drop on a narrow screen without also
                disappearing from the list, where it is the whole point. */}
            <SelectTrigger
              aria-label="Cryptocurrency"
              className="h-9 w-[124px] shrink-0 border-border bg-secondary sm:w-[190px] lg:w-[210px]"
            >
              <span className="flex min-w-0 items-center gap-2">
                <span className="font-semibold">{shownLabel}</span>
                <span className="hidden truncate text-xs text-muted-foreground sm:inline">
                  {pairName}
                </span>
              </span>
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
              <SelectItem value={ROBINHOOD_ETH}>
                <div className="flex w-full items-center justify-between">
                  <span className="font-semibold">ETH/USDG</span>
                  <span className="ml-2 text-xs text-muted-foreground">Ethereum · Robinhood Chain</span>
                </div>
              </SelectItem>
              {STOCKS.map((st) => (
                <SelectItem key={st.symbol} value={st.symbol}>
                  <div className="flex w-full items-center justify-between">
                    <span className="font-semibold">{st.symbol}</span>
                    <span className="ml-2 text-xs text-muted-foreground">{st.name} · stock</span>
                  </div>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          {onRobinhood && (
            <Button size="sm" className="h-8 shrink-0 gap-1.5 text-xs" onClick={() => openVault("WETH/USDG")}>
              <ShieldCheck className="h-3.5 w-3.5" /> Vault
            </Button>
          )}
          {spot !== undefined && (
            <span className="truncate text-sm tabular-nums text-foreground">
              ${formatPrice(spot)}
            </span>
          )}

          <span
            className="flex shrink-0 items-center gap-1.5 text-[11px] text-muted-foreground"
            title={live ? "Streaming live from Binance" : "Not connected to the live feed"}
          >
            <span
              className={`inline-block h-1.5 w-1.5 rounded-full ${
                live ? "animate-pulse bg-emerald-500" : "bg-muted-foreground/40"
              }`}
            />
            <span className="hidden sm:inline">{live ? "live" : "offline"}</span>
          </span>

          {/* Compact-only entrances to the rail and to the rest of the controls. */}
          <div className="ml-auto flex shrink-0 items-center gap-1 lg:hidden">
            <Button
              variant="ghost"
              size="sm"
              className="h-9 gap-1.5 px-2 text-xs"
              onClick={() => setRailOpen(true)}
            >
              <Layers className="h-4 w-4" />
              {railCount > 0 && <span className="tabular-nums">{railCount}</span>}
              <span className="sr-only">Levels and patterns</span>
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="h-9 w-9"
              onClick={() => setSettingsOpen(true)}
            >
              <SlidersHorizontal className="h-4 w-4" />
              <span className="sr-only">Chart settings</span>
            </Button>
          </div>
        </div>

        {/* Timeframes are the one control frequent enough to stay on the
            surface at every width. On a phone they take a row of their own and
            scroll if the pair list ever outgrows it; from sm there is room to
            sit beside the symbol. */}
        <div className="-mx-3 overflow-x-auto px-3 sm:mx-0 sm:overflow-visible sm:px-0 lg:hidden [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
          <div className="w-max">{timeframeControl}</div>
        </div>

        <div className="hidden items-center gap-2 lg:flex lg:flex-wrap">
          {timeframeControl}
          {controlGroups.map((g) => (
            <div key={g.key} className="contents">
              {g.node}
            </div>
          ))}
        </div>
      </div>

      {slots?.toolbar && (
        <div className="hidden flex-wrap items-center justify-between gap-2 px-4 pb-2 pt-3 lg:flex">
          <div className="flex items-baseline gap-3">
            <h2 className="text-lg font-semibold tracking-tight text-foreground">
              {onRobinhood ? "ETH / USDG" : `${selected.replace(/USDT$/, "")} / USDT`}
            </h2>
            {onRobinhood ? (
              <>
                <span className="rounded border border-primary/30 bg-primary/10 px-1.5 py-0.5 text-[10px] font-medium text-primary">
                  Robinhood Chain
                </span>
                <span className="font-mono text-[11px] text-muted-foreground">
                  {timeframe} · ETH price · trades in the WETH/USDG pool, from your vault
                </span>
                {/* The stock chart's button, so every Robinhood Chain asset offers its vault alike. */}
                <Button size="sm" className="h-8 gap-1.5 text-xs" onClick={() => openVault("WETH/USDG")}>
                  <ShieldCheck className="h-3.5 w-3.5" /> Trade ETH in your vault
                </Button>
              </>
            ) : (
              <span className="font-mono text-[11px] text-muted-foreground">
                {timeframe} · Binance spot reference
              </span>
            )}
          </div>
          {showPatterns && patterns[0] && (
            <span className="inline-flex items-center gap-1.5 rounded border border-primary/25 bg-primary/10 px-2.5 py-1 font-mono text-[11px] text-primary">
              <Sparkles className="h-3.5 w-3.5" />
              {patterns[0].kind}-pattern {patterns[0].state} · neck ${formatPrice(patterns[0].neckline)}
            </span>
          )}
        </div>
      )}

      <div className={`flex min-h-0 flex-1 ${slots?.toolbar ? "lg:mx-3 lg:overflow-hidden lg:rounded-lg" : ""}`}>
        {/* Chart */}
        <div className="relative min-w-0 flex-1">
          <div ref={containerRef} className="absolute inset-0" />
          <div className="pointer-events-none absolute left-2 right-16 top-2 z-20 lg:top-10">
            <IndicatorBar specs={indicators} onChange={setIndicators} />
          </div>
          {chartStyle === "candle" && (hovered ?? latest) && (
            <div className="pointer-events-none absolute left-2 top-2 z-10 hidden items-center gap-3 rounded bg-background/85 px-2 py-1 font-mono text-[11px] text-muted-foreground backdrop-blur lg:flex">
              {(["open", "high", "low", "close"] as const).map((k) => (
                <span key={k}>
                  {k[0].toUpperCase()}:{" "}
                  <strong
                    className="font-semibold"
                    style={{
                      color: k === "high" ? SUPPORT : k === "low" ? RESISTANCE : k === "close" ? INK : undefined,
                    }}
                  >
                    {formatPrice((hovered ?? latest)![k])}
                  </strong>
                </span>
              ))}
            </div>
          )}
          {showPatterns && (
            <PatternOverlay
              chart={chartRef.current}
              series={seriesRef.current}
              patterns={patterns}
            />
          )}
          {marks.length > 0 && (
            <MarkOverlay chart={chartRef.current} series={seriesRef.current} marks={marks} loading={loading} />
          )}
          {positions.length > 0 && !loading && (
            <PositionOverlay
              chart={chartRef.current}
              series={seriesRef.current}
              positions={positions}
              timeframeSeconds={TF_SECONDS[timeframe] ?? 3600}
            />
          )}
          {loading && (
            <div className="pointer-events-none absolute inset-0 grid place-items-center text-sm text-muted-foreground">
              Loading {selected} {timeframe}…
            </div>
          )}
          {error && (
            <div className="absolute inset-x-0 top-2 mx-auto w-fit max-w-[90%] rounded-md border border-border bg-card/95 px-3 py-1.5 text-center text-xs text-muted-foreground">
              {error}
            </div>
          )}
        </div>

        {/* Level rail - beside the chart, unless the page gave it a slot. */}
        {!slots?.rail && (
          <div className="hidden w-[190px] shrink-0 overflow-y-auto border-l border-border px-3 py-3 lg:block">
            {railContent}
          </div>
        )}
      </div>

      {/* Legend - identity is never colour alone. The written keys below are
          desktop-only: on a phone they cost a line of chart each, and the
          strength of every level is spelled out in words in the sheet. */}
      <div
        className={`flex flex-wrap items-center gap-x-5 gap-y-1 border-t border-border px-3 py-2 text-[11px] text-muted-foreground lg:px-4 ${
          slots?.toolbar ? "lg:border-t-0 lg:py-3" : ""
        }`}
      >
        {chartStyle === "candle" && (
          <>
            <span className="flex shrink-0 items-center gap-1.5">
              <svg width="9" height="13" aria-hidden>
                <rect x="0.5" y="0.5" width="8" height="12" fill={SURFACE} stroke={SUPPORT} />
              </svg>
              up (hollow)
            </span>
            <span className="flex shrink-0 items-center gap-1.5">
              <svg width="9" height="13" aria-hidden>
                <rect x="0.5" y="0.5" width="8" height="12" fill={RESISTANCE} stroke={RESISTANCE} />
              </svg>
              down (filled)
            </span>
          </>
        )}

        {showPatterns && (
          <span className="flex shrink-0 items-center gap-1.5">
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
        <span className="flex shrink-0 items-center gap-1.5">
          <svg width="16" height="8" aria-hidden>
            <line x1="0" y1="4" x2="16" y2="4" stroke={SUPPORT} strokeWidth="2" />
          </svg>
          support
        </span>
        <span className="flex shrink-0 items-center gap-1.5">
          <svg width="16" height="8" aria-hidden>
            <line x1="0" y1="4" x2="16" y2="4" stroke={RESISTANCE} strokeWidth="2" />
          </svg>
          resistance
        </span>
        <span className="hidden shrink-0 text-muted-foreground/70 lg:inline">
          solid = strong · dashed = medium · dotted = weak · scroll to zoom, drag to pan
        </span>
      </div>

      {slots?.toolbar && createPortal(desktopToolbar, slots.toolbar)}
      {slots?.detection && createPortal(detectionContent, slots.detection)}
      {slots?.rail && createPortal(railContent, slots.rail)}

      {/* Compact-width sheets. Neither is reachable at lg, where the same
          content is already on screen. */}
      <Sheet open={settingsOpen} onOpenChange={setSettingsOpen}>
        <SheetContent
          side="bottom"
          className="max-h-[85dvh] gap-0 overflow-y-auto rounded-t-xl border-border bg-card p-0 lg:hidden"
        >
          <SheetHeader className="border-b border-border px-4 py-3 text-left">
            <SheetTitle className="text-sm">Chart settings</SheetTitle>
            <SheetDescription className="text-xs">
              What the chart draws, and how hard it looks for it.
            </SheetDescription>
          </SheetHeader>
          <div className="px-4 pb-[calc(1rem+env(safe-area-inset-bottom))]">
            {controlGroups.map((g) => (
              <div
                key={g.key}
                className="flex items-center justify-between gap-3 border-b border-border/60 py-3 last:border-0"
              >
                <span className="text-xs text-muted-foreground">{g.label}</span>
                {g.node}
              </div>
            ))}
          </div>
        </SheetContent>
      </Sheet>

      <Sheet open={railOpen} onOpenChange={setRailOpen}>
        <SheetContent
          side="bottom"
          className="max-h-[75dvh] gap-0 overflow-y-auto rounded-t-xl border-border bg-card p-0 lg:hidden"
        >
          <SheetHeader className="border-b border-border px-4 py-3 text-left">
            <SheetTitle className="text-sm">Levels and patterns</SheetTitle>
            <SheetDescription className="text-xs">
              What the analysis found in the range you are looking at.
            </SheetDescription>
          </SheetHeader>
          <div className="px-4 py-4 pb-[calc(1rem+env(safe-area-inset-bottom))]">{railContent}</div>
        </SheetContent>
      </Sheet>
    </div>
  )
}

/*
 * One renderer for every segmented button group in the toolbar. Targets are
 * finger-sized by default and tighten to the original desktop metrics at lg,
 * where a pointer can hit a 24px button and the whole row has to fit.
 */
function Segmented<T extends string>({
  options,
  value,
  onChange,
  ariaLabel,
  title,
  mono,
}: {
  options: readonly T[]
  value: T
  onChange: (v: T) => void
  ariaLabel: string
  title?: (option: T) => string
  mono?: boolean
}) {
  return (
    <div
      role="group"
      aria-label={ariaLabel}
      className="flex shrink-0 overflow-hidden rounded-md border border-border"
    >
      {options.map((option) => (
        <button
          key={option}
          type="button"
          onClick={() => onChange(option)}
          aria-pressed={option === value}
          title={title?.(option)}
          className={`px-3 py-2 text-xs transition-colors lg:py-1 ${
            mono ? "font-mono lg:px-2.5" : "capitalize lg:px-2"
          } ${
            option === value
              ? "bg-secondary text-foreground"
              : "text-muted-foreground hover:text-foreground"
          }`}
        >
          {option}
        </button>
      ))}
    </div>
  )
}

/** 1,840,000,000 -> "1.84B". */
function compactUsd(value: number): string {
  return new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 2 }).format(value)
}
