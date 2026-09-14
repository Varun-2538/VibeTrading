"use client"

import type React from "react"

import { useState } from "react"
import TradingViewChart from "@/components/trading-view-chart"
import ChatPanel from "@/components/chat-panel"
import AnalysisPanel from "@/components/analysis-panel"
import { Button } from "@/components/ui/button"
import { MessageSquare } from "lucide-react"

export default function TradingDashboard() {
  const [isChatOpen, setIsChatOpen] = useState(true)
  const [chatWidth, setChatWidth] = useState(380)
  const [analysisHeight, setAnalysisHeight] = useState(300)
  const [isDraggingChat, setIsDraggingChat] = useState(false)
  const [isDraggingAnalysis, setIsDraggingAnalysis] = useState(false)
  const [currentSymbol, setCurrentSymbol] = useState("BTCUSDT")

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

  return (
    <div className="h-screen w-full overflow-hidden bg-background">
      {!isChatOpen && (
        <Button
          onClick={() => setIsChatOpen(true)}
          size="icon"
          className="fixed top-4 right-4 z-50 bg-primary hover:bg-primary/90 text-primary-foreground shadow-lg"
        >
          <MessageSquare className="h-5 w-5" />
        </Button>
      )}

      <div
        className="h-full grid gap-0"
        style={{
          gridTemplateColumns: isChatOpen ? `1fr ${chatWidth}px` : "1fr",
          gridTemplateRows: `1fr ${analysisHeight}px`,
        }}
      >
        {/* Top Left: TradingView Chart */}
        <div className="border-r border-b border-border relative">
          <TradingViewChart symbol={currentSymbol} onSymbolChange={setCurrentSymbol} />
        </div>

        {isChatOpen && (
          <>
            <div className="row-span-2 border-l border-border relative">
              {/* Resize Handle */}
              <div
                onMouseDown={handleChatResize}
                className={`absolute left-0 top-0 bottom-0 w-1 cursor-col-resize hover:bg-primary/50 transition-colors z-10 ${
                  isDraggingChat ? "bg-primary" : ""
                }`}
              >
                <div className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 w-1 h-12 bg-border rounded-full" />
              </div>
              <ChatPanel
                onClose={() => setIsChatOpen(false)}
                currentSymbol={currentSymbol}
                onSymbolChange={setCurrentSymbol}
              />
            </div>
          </>
        )}

        <div className="border-t border-border relative">
          {/* Resize Handle */}
          <div
            onMouseDown={handleAnalysisResize}
            className={`absolute left-0 right-0 top-0 h-1 cursor-row-resize hover:bg-primary/50 transition-colors z-10 ${
              isDraggingAnalysis ? "bg-primary" : ""
            }`}
          >
            <div className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 h-1 w-12 bg-border rounded-full" />
          </div>
          <AnalysisPanel />
        </div>
      </div>
    </div>
  )
}
