"use client"

import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Send, Sparkles, X, Loader2, Check, XIcon } from "lucide-react"

interface LiquidityLevel {
  price: number
  strength: string
}

interface LiquidityData {
  current_price: number
  support_levels: LiquidityLevel[]
  resistance_levels: LiquidityLevel[]
}

interface Message {
  id: string
  role: "user" | "assistant"
  content: string
  symbol?: string
  liquidityData?: LiquidityData
  showActions?: boolean
}

interface ChatPanelProps {
  onClose: () => void
  currentSymbol?: string
  onSymbolChange?: (symbol: string) => void
  onMarkLevels?: (data: { symbol: string; liquidityData: LiquidityData }) => void
}

export default function ChatPanel({ onClose, currentSymbol, onSymbolChange, onMarkLevels }: ChatPanelProps) {
  const [messages, setMessages] = useState<Message[]>([
    {
      id: "1",
      role: "assistant",
      content:
        "Hello! I'm your AI trading assistant powered by Cerebras AI. Ask me about:\n\n• Liquidity levels (support & resistance)\n• Technical indicators (RSI, MACD, EMA)\n• Trading strategies\n• Cryptocurrency analysis\n\nAvailable: BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT, XRPUSDT, ADAUSDT, DOGEUSDT, DOTUSDT, AVAXUSDT",
    },
  ])
  const [input, setInput] = useState("")
  const [isLoading, setIsLoading] = useState(false)

  const handleSend = async () => {
    if (!input.trim() || isLoading) return

    const userMessage: Message = {
      id: Date.now().toString(),
      role: "user",
      content: input,
    }

    setMessages((prev) => [...prev, userMessage])
    const userInput = input
    setInput("")
    setIsLoading(true)

    try {
      // Call backend chat API
      const response = await fetch("http://localhost:8000/api/chat/ask", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          message: userInput,
          symbol: currentSymbol,
          timeframe: "1h",
        }),
      })

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`)
      }

      const data = await response.json()

      // Check if response contains liquidity data
      const hasLiquidityData = data.data && (data.data.support_levels || data.data.resistance_levels)

      // Add AI response
      const aiMessage: Message = {
        id: (Date.now() + 1).toString(),
        role: "assistant",
        content: data.response,
        symbol: data.symbol,
        liquidityData: hasLiquidityData ? data.data : undefined,
        showActions: hasLiquidityData, // Show Accept/Reject buttons if liquidity data exists
      }

      setMessages((prev) => [...prev, aiMessage])

      // Update chart symbol if changed
      if (data.symbol && data.chart_update && onSymbolChange) {
        onSymbolChange(data.symbol)
      }
    } catch (error) {
      console.error("Error:", error)
      const errorMessage: Message = {
        id: (Date.now() + 1).toString(),
        role: "assistant",
        content: "Sorry, I encountered an error. Please make sure backend is running on http://localhost:8000",
      }
      setMessages((prev) => [...prev, errorMessage])
    } finally {
      setIsLoading(false)
    }
  }

  const handleAcceptLevels = (messageId: string) => {
    const message = messages.find((m) => m.id === messageId)
    if (message && message.liquidityData && message.symbol && onMarkLevels) {
      onMarkLevels({
        symbol: message.symbol,
        liquidityData: message.liquidityData,
      })

      // Hide action buttons after accepting
      setMessages((prev) =>
        prev.map((m) => (m.id === messageId ? { ...m, showActions: false } : m))
      )
    }
  }

  const handleRejectLevels = (messageId: string) => {
    // Just hide the action buttons
    setMessages((prev) =>
      prev.map((m) => (m.id === messageId ? { ...m, showActions: false } : m))
    )
  }

  return (
    <div className="flex h-full flex-col bg-card">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <div className="flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-primary" />
          <h2 className="text-sm font-semibold text-foreground">AI Assistant</h2>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <div className={`h-2 w-2 rounded-full ${isLoading ? "bg-yellow-500 animate-pulse" : "bg-green-500"}`} />
            <span className="text-xs text-muted-foreground">{isLoading ? "Thinking..." : "Online"}</span>
          </div>
          <Button onClick={onClose} size="icon" variant="ghost" className="h-7 w-7">
            <X className="h-4 w-4" />
          </Button>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-hidden">
        <ScrollArea className="h-full px-4 py-4">
          <div className="space-y-4">
            {messages.map((message) => (
              <div key={message.id} className={`flex ${message.role === "user" ? "justify-end" : "justify-start"}`}>
                <div className={`max-w-[85%] ${message.role === "user" ? "" : "w-full"}`}>
                  <div
                    className={`rounded-lg px-4 py-2.5 ${
                      message.role === "user"
                        ? "bg-primary text-primary-foreground"
                        : "bg-secondary text-secondary-foreground"
                    }`}
                  >
                    {message.symbol && message.role === "assistant" && (
                      <div className="text-xs font-semibold mb-1 opacity-70">{message.symbol}</div>
                    )}
                    <div className="text-sm leading-relaxed whitespace-pre-line">{message.content}</div>
                  </div>

                  {/* Accept/Reject Buttons for Liquidity Levels */}
                  {message.role === "assistant" && message.showActions && message.liquidityData && (
                    <div className="mt-3 flex gap-2">
                      <Button
                        size="sm"
                        onClick={() => handleAcceptLevels(message.id)}
                        className="flex-1 bg-green-600 hover:bg-green-700 text-white"
                      >
                        <Check className="h-4 w-4 mr-1" />
                        Mark on Chart
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => handleRejectLevels(message.id)}
                        className="flex-1 border-red-500/50 text-red-500 hover:bg-red-500/10"
                      >
                        <XIcon className="h-4 w-4 mr-1" />
                        Dismiss
                      </Button>
                    </div>
                  )}
                </div>
              </div>
            ))}
            {isLoading && (
              <div className="flex justify-start">
                <div className="bg-secondary text-secondary-foreground rounded-lg px-4 py-2.5">
                  <Loader2 className="h-4 w-4 animate-spin" />
                </div>
              </div>
            )}
          </div>
        </ScrollArea>
      </div>

      {/* Input Area */}
      <div className="border-t border-border p-4">
        <div className="flex gap-2">
          <Input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyPress={(e) => e.key === "Enter" && !e.shiftKey && handleSend()}
            placeholder="Ask about liquidity levels, strategies..."
            className="flex-1 bg-secondary border-border"
            disabled={isLoading}
          />
          <Button onClick={handleSend} size="icon" disabled={isLoading || !input.trim()}>
            {isLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
          </Button>
        </div>
        <p className="mt-2 text-xs text-muted-foreground">
          Powered by Cerebras AI • Try: "Show me liquidity levels for Bitcoin"
        </p>
      </div>
    </div>
  )
}
