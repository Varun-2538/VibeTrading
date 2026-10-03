"use client"

import type React from "react"

import { useState } from "react"
import PriceChart from "@/components/price-chart"
import ChatPanel from "@/components/chat-panel"
import AnalysisPanel from "@/components/analysis-panel"
import { Button } from "@/components/ui/button"
import { BarChart3, CandlestickChart, MessageSquare, Sparkles } from "lucide-react"
import type { LiquidityData } from "@/lib/api"

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

export default function TradingDashboard() {
  const [isChatOpen, setIsChatOpen] = useState(true)
  const [chatWidth, setChatWidth] = useState(380)
  const [analysisHeight, setAnalysisHeight] = useState(300)
  const [isDraggingChat, setIsDraggingChat] = useState(false)
  const [isDraggingAnalysis, setIsDraggingAnalysis] = useState(false)
  const [region, setRegion] = useState<CompactRegion>("chart")
  const [currentSymbol, setCurrentSymbol] = useState("BTCUSDT")
  const [markedLevels, setMarkedLevels] = useState<{
    symbol: string
    liquidityData: LiquidityData
  } | null>(null)

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
    <div className="flex h-[100dvh] w-full flex-col overflow-hidden overscroll-none bg-background">
      {!isChatOpen && (
        <Button
          onClick={() => setIsChatOpen(true)}
          size="icon"
          className="fixed top-4 right-4 z-50 hidden bg-primary text-primary-foreground shadow-lg hover:bg-primary/90 lg:inline-flex"
        >
          <MessageSquare className="h-5 w-5" />
          <span className="sr-only">Open the assistant</span>
        </Button>
      )}

      <div
        className={`relative min-h-0 flex-1 lg:grid lg:gap-0 lg:grid-rows-[1fr_var(--analysis-h)] ${
          isChatOpen ? "lg:grid-cols-[1fr_var(--chat-w)]" : "lg:grid-cols-1"
        }`}
        style={
          {
            "--chat-w": `${chatWidth}px`,
            "--analysis-h": `${analysisHeight}px`,
          } as React.CSSProperties
        }
      >
        {/* Chart. Never hidden, at any width: a chart taken out of the flow
            loses its size and has to re-measure when it comes back. */}
        <div className="absolute inset-0 lg:relative lg:inset-auto lg:col-start-1 lg:row-start-1 lg:border-r lg:border-b lg:border-border">
          <PriceChart
            symbol={currentSymbol}
            onSymbolChange={setCurrentSymbol}
            liquidityData={markedLevels}
            onClearLevels={() => setMarkedLevels(null)}
          />
        </div>

        {/* Analysis: a row under the chart at lg, a full-screen region below it. */}
        <div
          className={`absolute inset-0 z-20 bg-card lg:relative lg:inset-auto lg:z-auto lg:col-start-1 lg:row-start-2 lg:block lg:border-t lg:border-border ${
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
          <AnalysisPanel />
        </div>

        {/* Chat: a resizable column at lg, a full-screen region below it. */}
        <div
          className={`absolute inset-0 z-30 bg-card lg:relative lg:inset-auto lg:z-auto lg:col-start-2 lg:row-span-2 lg:row-start-1 lg:border-l lg:border-border ${
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
            currentSymbol={currentSymbol}
            onSymbolChange={setCurrentSymbol}
            onMarkLevels={setMarkedLevels}
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
                active ? "text-foreground" : "text-muted-foreground"
              }`}
            >
              <span
                aria-hidden
                className={`absolute inset-x-0 top-0 h-px ${active ? "bg-foreground" : "bg-transparent"}`}
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
