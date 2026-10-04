"use client"

import type React from "react"

import { useCallback, useEffect, useMemo, useState } from "react"
import PriceChart, { type PanelSlots } from "@/components/price-chart"
import ChatPanel from "@/components/chat-panel"
import AnalysisPanel from "@/components/analysis-panel"
import AppHeader from "@/components/app-header"
import Watchlist, { WATCHLIST } from "@/components/watchlist"
import StockChart from "@/components/stock-chart"
import { OPEN_VAULT_EVENT, fetchStockQuotes, isStock, stockFor } from "@/lib/stocks"
import { Button } from "@/components/ui/button"
import { BarChart3, CandlestickChart, Cpu, MessageSquare, Sparkles } from "lucide-react"
import type { LiquidityData, Timeframe } from "@/lib/api"
import type { Mark, PatternSettings, Viewport } from "@/lib/marks"
import { TRADE_MARKS_EVENT, type TradeMarksDetail } from "@/lib/backtests"
import { subscribeTickers, type Ticker } from "@/lib/binance"

/*
 * Two layouts, one tree.
 *
 * At lg and above this is the four-region terminal it has always been: chart
 * and rail, a chat column you can drag wider, an analysis row you can drag
 * taller. Below lg none of that survives contact with a phone, and the reason
 * is not width - it is that a chart canvas owns its touch gestures. Put it in
 * a scrolling page and every attempt to pan the chart scrolls the page
 * instead. So the compact layout gives the chart the whole viewport, never
 * scrolls, and floats the other regions over it from a bottom bar.
 *
 * Every region stays mounted at both sizes and is hidden with display:none
 * rather than unmounted, which is what keeps the websocket connected, the
 * chart from re-initialising, and - closing a gap the desktop layout had -
 * the conversation from being thrown away every time the chat is closed.
 */
type CompactRegion = "chart" | "analysis" | "chat"

const REGIONS: { id: CompactRegion; label: string; Icon: typeof CandlestickChart }[] = [
  { id: "chart", label: "Chart", Icon: CandlestickChart },
  { id: "analysis", label: "Analysis", Icon: BarChart3 },
  { id: "chat", label: "Assistant", Icon: Sparkles },
]

const NO_MARKS: Mark[] = []

const TIMEFRAME_MS: Record<Timeframe, number> = {
  "1m": 60_000,
  "5m": 300_000,
  "15m": 900_000,
  "1h": 3_600_000,
  "4h": 14_400_000,
  "1d": 86_400_000,
}

/*
 * The side rail only earns its width at xl. Between lg and xl the chart keeps
 * its level rail and pattern settings inline, as it always has, so the slots
 * are handed over only when the rail is actually on screen.
 */
const WIDE = "(min-width: 1280px)"
const DESKTOP = "(min-width: 1024px)"

function useMedia(query: string) {
  const [matches, setMatches] = useState(false)
  useEffect(() => {
    const mql = window.matchMedia(query)
    const onChange = () => setMatches(mql.matches)
    onChange()
    mql.addEventListener("change", onChange)
    return () => mql.removeEventListener("change", onChange)
  }, [query])
  return matches
}

export default function TradingDashboard() {
  const [isChatOpen, setIsChatOpen] = useState(true)
  const [chatWidth, setChatWidth] = useState(380)
  const [analysisHeight, setAnalysisHeight] = useState(300)
  const [isDraggingChat, setIsDraggingChat] = useState(false)
  const [isDraggingAnalysis, setIsDraggingAnalysis] = useState(false)
  const [region, setRegion] = useState<CompactRegion>("chart")
  const [currentSymbol, setCurrentSymbol] = useState("BTCUSDT")
  // The last crypto pair picked. A stock replaces the chart, but the level and
  // pattern analysis, the assistant and the rules read Binance and have never seen
  // a stock, so they stay on this pair rather than failing on one they cannot read.
  const [cryptoSymbol, setCryptoSymbol] = useState("BTCUSDT")
  const selectSymbol = useCallback((symbol: string) => {
    setCurrentSymbol(symbol)
    if (!isStock(symbol)) setCryptoSymbol(symbol)
  }, [])
  const stock = stockFor(currentSymbol)
  // Lifted out of the chart so the strategy panel builds rules against the
  // timeframe the user is actually looking at.
  const [timeframe, setTimeframe] = useState<Timeframe>("1h")
  const [markedLevels, setMarkedLevels] = useState<{
    symbol: string
    liquidityData: LiquidityData
  } | null>(null)
  // What the chart is showing, so the assistant answers about exactly those
  // candles with exactly the detector settings that are drawn.
  const [viewport, setViewport] = useState<Viewport | null>(null)
  const [patternSettings, setPatternSettings] = useState<PatternSettings>({
    strictness: "balanced",
    source: "wick",
    scale: "swing",
  })
  // Drawings the assistant was asked to make. Already grounded server-side.
  const [marks, setMarks] = useState<Mark[]>([])
  // Trades a backtest report asked to draw, tied to the pair and timeframe
  // they happened on: drawn only while the chart shows that series.
  const [tradeMarks, setTradeMarks] = useState<TradeMarksDetail | null>(null)
  // One 24h ticker stream for all nine pairs: the watchlist and the top bar.
  const [tickers, setTickers] = useState<Record<string, Ticker>>({})
  useEffect(
    () => subscribeTickers(WATCHLIST, (t) => setTickers((prev) => ({ ...prev, [t.symbol]: t }))),
    [],
  )
  // Stock Tokens have no stream; their pools are polled once a minute.
  const [stockTickers, setStockTickers] = useState<Record<string, Ticker>>({})
  useEffect(() => {
    let alive = true
    const load = () =>
      fetchStockQuotes()
        .then((q) => alive && setStockTickers(q))
        .catch(() => undefined)
    void load()
    const id = window.setInterval(load, 60_000)
    return () => {
      alive = false
      window.clearInterval(id)
    }
  }, [])
  // "Trade in vault" from a stock chart lands on the panel that holds the vault.
  useEffect(() => {
    const onOpenVault = () => setRegion("analysis")
    window.addEventListener(OPEN_VAULT_EVENT, onOpenVault)
    return () => window.removeEventListener(OPEN_VAULT_EVENT, onOpenVault)
  }, [])

  const desktop = useMedia(DESKTOP)
  const wide = useMedia(WIDE)
  const [toolbarEl, setToolbarEl] = useState<HTMLDivElement | null>(null)
  const [detectionEl, setDetectionEl] = useState<HTMLDivElement | null>(null)
  const [railEl, setRailEl] = useState<HTMLDivElement | null>(null)
  const slots = useMemo<PanelSlots>(
    () => ({
      toolbar: desktop ? toolbarEl : null,
      detection: wide ? detectionEl : null,
      rail: wide ? railEl : null,
    }),
    [desktop, wide, toolbarEl, detectionEl, railEl],
  )
  const candlesInView = viewport
    ? Math.max(0, Math.round((viewport.to - viewport.from) / TIMEFRAME_MS[timeframe]) + 1)
    : null
  const ticker = tickers[cryptoSymbol]

  const clearMarks = useCallback(() => {
    setMarks([])
    setTradeMarks(null)
  }, [])

  useEffect(() => {
    const onTrades = (event: Event) => {
      const detail = (event as CustomEvent<TradeMarksDetail>).detail
      selectSymbol(detail.symbol)
      setTimeframe(detail.timeframe as Timeframe)
      setTradeMarks(detail)
      setRegion("chart")
    }
    window.addEventListener(TRADE_MARKS_EVENT, onTrades)
    return () => window.removeEventListener(TRADE_MARKS_EVENT, onTrades)
  }, [selectSymbol])

  const shownTradeMarks =
    tradeMarks && tradeMarks.symbol === cryptoSymbol && tradeMarks.timeframe === timeframe
      ? (tradeMarks.marks as Mark[])
      : NO_MARKS
  const chartMarks = useMemo(
    () => (shownTradeMarks.length ? [...marks, ...shownTradeMarks] : marks),
    [marks, shownTradeMarks],
  )

  const handleChatResize = (e: React.MouseEvent) => {
    e.preventDefault()
    setIsDraggingChat(true)

    const startX = e.clientX
    const startWidth = chatWidth

    const handleMouseMove = (e: MouseEvent) => {
      const diff = startX - e.clientX
      const newWidth = Math.max(300, Math.min(800, startWidth + diff))
      setChatWidth(newWidth)
    }

    const handleMouseUp = () => {
      setIsDraggingChat(false)
      document.removeEventListener("mousemove", handleMouseMove)
      document.removeEventListener("mouseup", handleMouseUp)
    }

    document.addEventListener("mousemove", handleMouseMove)
    document.addEventListener("mouseup", handleMouseUp)
  }

  const handleAnalysisResize = (e: React.MouseEvent) => {
    e.preventDefault()
    setIsDraggingAnalysis(true)

    const startY = e.clientY
    const startHeight = analysisHeight

    const handleMouseMove = (e: MouseEvent) => {
      const diff = startY - e.clientY
      const newHeight = Math.max(200, Math.min(600, startHeight + diff))
      setAnalysisHeight(newHeight)
    }

    const handleMouseUp = () => {
      setIsDraggingAnalysis(false)
      document.removeEventListener("mousemove", handleMouseMove)
      document.removeEventListener("mouseup", handleMouseUp)
    }

    document.addEventListener("mousemove", handleMouseMove)
    document.addEventListener("mouseup", handleMouseUp)
  }

  // Closing the chat means the same thing at both sizes: go back to the chart.
  const closeChat = () => {
    setIsChatOpen(false)
    setRegion("chart")
  }

  return (
    // dvh, not vh: on mobile browsers vh counts the retracted URL bar, which
    // pushes the bottom bar off the screen until you scroll - and this page
    // never scrolls. overscroll-none stops a downward drag on the chart from
    // triggering pull-to-refresh.
    <div className="vt vt-panel flex h-[100dvh] w-full flex-col overflow-hidden overscroll-none bg-background">
      <AppHeader onNavigate={() => setRegion("analysis")} />

      {!isChatOpen && (
        <Button
          onClick={() => setIsChatOpen(true)}
          size="icon"
          className="fixed bottom-5 right-5 z-50 hidden bg-primary text-primary-foreground shadow-lg hover:bg-primary/90 lg:inline-flex"
        >
          <MessageSquare className="h-5 w-5" />
          <span className="sr-only">Open the assistant</span>
        </Button>
      )}

      {/* Desktop top bar. The chart renders its toolbar into it. */}
      <div className="hidden shrink-0 px-2 pt-2 lg:block">
        <div className="flex items-center gap-3 rounded-xl border border-border bg-card px-3 py-2">
          {/* The crypto chart portals its toolbar here. While a stock is on
              screen the stock chart carries its own, so this one steps aside. */}
          <div ref={setToolbarEl} className={`min-w-0 flex-1 ${stock ? "hidden" : ""}`} />
          {stock && (
            <span className="min-w-0 flex-1 truncate font-mono text-xs text-muted-foreground">
              {stock.symbol} · Robinhood Stock Token · Robinhood Chain
            </span>
          )}
          {candlesInView !== null && (
            <span className="hidden shrink-0 items-center gap-1.5 rounded bg-muted px-2.5 py-1 font-mono text-[10px] uppercase tracking-[0.06em] text-muted-foreground xl:flex">
              <Cpu className="h-3.5 w-3.5 text-primary/80" />
              {candlesInView} candles in view
            </span>
          )}
        </div>
      </div>

      <div
        className={`relative min-h-0 flex-1 lg:grid lg:gap-2 lg:p-2 lg:grid-rows-[minmax(0,1fr)_var(--analysis-h)] ${
          isChatOpen
            ? "lg:grid-cols-[minmax(0,1fr)_var(--chat-w)] xl:grid-cols-[240px_minmax(0,1fr)_var(--chat-w)]"
            : "lg:grid-cols-1 xl:grid-cols-[240px_minmax(0,1fr)]"
        }`}
        style={
          {
            "--chat-w": `${chatWidth}px`,
            "--analysis-h": `${analysisHeight}px`,
          } as React.CSSProperties
        }
      >
        {/* Side rail, xl only: the watchlist, and the chart's pattern
            settings and level rail rendered here through portals. */}
        <aside className="hidden min-h-0 flex-col gap-2 overflow-y-auto xl:col-start-1 xl:row-span-2 xl:row-start-1 xl:flex">
          <Watchlist
            tickers={tickers}
            stockTickers={stockTickers}
            selected={currentSymbol}
            onSelect={selectSymbol}
          />
          <section className="shrink-0 rounded-xl border border-border bg-card p-3">
            <h2 className="mb-3 font-mono text-[10px] font-semibold uppercase tracking-[0.08em] text-primary/80">
              Detection parameters
            </h2>
            <div ref={setDetectionEl} />
          </section>
          <section className="shrink-0 rounded-xl border border-border bg-card p-3">
            <div ref={setRailEl} />
          </section>
        </aside>

        {/* Chart. Never hidden, at any width: a chart taken out of the flow
            loses its size and has to re-measure when it comes back. */}
        <div className="absolute inset-0 lg:relative lg:inset-auto lg:col-start-1 lg:row-start-1 lg:overflow-hidden lg:rounded-xl lg:border lg:border-border xl:col-start-2">
          <PriceChart
            symbol={cryptoSymbol}
            onSymbolChange={selectSymbol}
            timeframe={timeframe}
            onTimeframeChange={setTimeframe}
            liquidityData={markedLevels}
            onClearLevels={() => setMarkedLevels(null)}
            onViewportChange={setViewport}
            onPatternSettingsChange={setPatternSettings}
            marks={chartMarks}
            onClearMarks={clearMarks}
            slots={slots}
            changePct={ticker?.changePct}
            quoteVolume={ticker?.quoteVolume}
          />
          {/* A stock covers the crypto chart rather than replacing it, so that one
              keeps its size and its stream and is exactly as it was on return. */}
          {stock && (
            <div className="absolute inset-0 z-10">
              <StockChart
                stock={stock}
                quote={stockTickers[stock.symbol]}
                timeframe={timeframe}
                onTimeframeChange={setTimeframe}
                onSymbolChange={selectSymbol}
              />
            </div>
          )}
        </div>

        {/* Analysis: a card under the chart at lg, a full-screen region below it. */}
        <div
          className={`absolute inset-0 z-20 bg-card lg:relative lg:inset-auto lg:z-auto lg:col-start-1 lg:row-start-2 lg:block lg:overflow-hidden lg:rounded-xl lg:border lg:border-border xl:col-start-2 ${
            region === "analysis" ? "" : "hidden"
          }`}
        >
          {/* Drag to resize is a pointer affordance; on touch there is nothing
              to grab and nothing to resize, so it does not exist there. */}
          <div
            onMouseDown={handleAnalysisResize}
            className={`absolute left-0 right-0 top-0 z-10 hidden h-1 cursor-row-resize transition-colors hover:bg-primary/50 lg:block ${
              isDraggingAnalysis ? "bg-primary" : ""
            }`}
          >
            <div className="absolute left-1/2 top-1/2 h-1 w-12 -translate-x-1/2 -translate-y-1/2 rounded-full bg-border" />
          </div>
          <AnalysisPanel symbol={cryptoSymbol} timeframe={timeframe} />
        </div>

        {/* Chat: a resizable card at lg, a full-screen region below it. */}
        <div
          className={`absolute inset-0 z-30 bg-card lg:relative lg:inset-auto lg:z-auto lg:col-start-2 lg:row-span-2 lg:row-start-1 lg:overflow-hidden lg:rounded-xl lg:border lg:border-border xl:col-start-3 ${
            region === "chat" ? "" : "hidden"
          } ${isChatOpen ? "lg:block" : "lg:hidden"}`}
        >
          <div
            onMouseDown={handleChatResize}
            className={`absolute left-0 top-0 bottom-0 z-10 hidden w-1 cursor-col-resize transition-colors hover:bg-primary/50 lg:block ${
              isDraggingChat ? "bg-primary" : ""
            }`}
          >
            <div className="absolute left-1/2 top-1/2 h-12 w-1 -translate-x-1/2 -translate-y-1/2 rounded-full bg-border" />
          </div>
          <ChatPanel
            onClose={closeChat}
            currentSymbol={cryptoSymbol}
            onSymbolChange={selectSymbol}
            onMarkLevels={setMarkedLevels}
            timeframe={timeframe}
            viewport={viewport}
            patternSettings={patternSettings}
            onMarks={setMarks}
          />
        </div>
      </div>

      {/* Compact-width region switcher. Flush and hairline-ruled to match the
          rest of the panel's chrome rather than arriving as app furniture. */}
      <nav
        aria-label="Panel"
        className="flex shrink-0 border-t border-border bg-card pb-[env(safe-area-inset-bottom)] lg:hidden"
      >
        {REGIONS.map(({ id, label, Icon }) => {
          const active = region === id
          return (
            <button
              key={id}
              type="button"
              aria-current={active ? "page" : undefined}
              onClick={() => {
                setRegion(id)
                if (id === "chat") setIsChatOpen(true)
              }}
              className={`relative flex flex-1 flex-col items-center gap-1 py-2.5 text-[11px] transition-colors ${
                active ? "text-primary" : "text-muted-foreground"
              }`}
            >
              <span
                aria-hidden
                className={`absolute inset-x-0 top-0 h-px ${active ? "bg-primary" : "bg-transparent"}`}
              />
              <Icon className="h-4 w-4" />
              {label}
            </button>
          )
        })}
      </nav>
    </div>
  )
}
