"use client"

import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Send, Sparkles, X, Loader2, Check, XIcon, Bell } from "lucide-react"
import { API_BASE } from "@/lib/api"
import {
  announceRulesChanged,
  createRule,
  UnauthorizedError,
  type RuleDraft,
} from "@/lib/rules"

interface LiquidityLevel {
  price: number
  strength: string
  test_count?: number
  distance_pct?: number
}

interface LiquidityData {
  current_price: number
  support_levels: LiquidityLevel[]
  resistance_levels: LiquidityLevel[]
}

/** A rule the assistant read from a sentence, waiting for the user to arm it. */
interface DraftCard {
  draft: RuleDraft
  summary: string
  status: "pending" | "arming" | "armed" | "dismissed"
  error?: string
}

interface Message {
  id: string
  role: "user" | "assistant"
  content: string
  symbol?: string
  liquidityData?: LiquidityData
  showActions?: boolean
  ruleDraft?: DraftCard
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
        "Hello! I'm your AI trading assistant. Ask me about:\n\n• Liquidity levels (support & resistance)\n• Technical indicators (RSI, MACD, EMA)\n• Trading strategies\n• Cryptocurrency analysis\n\nAvailable: BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT, XRPUSDT, ADAUSDT, DOGEUSDT, DOTUSDT, AVAXUSDT",
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
      const response = await fetch(`${API_BASE}/api/chat/ask`, {
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

      // A drafted rule rides in data.rule_draft. It is shown, not armed: the
      // model may have misread the sentence, and the card is where that gets
      // caught.
      const ruleDraft: DraftCard | undefined = data.data?.rule_draft
        ? { draft: data.data.rule_draft, summary: data.data.summary ?? "", status: "pending" }
        : undefined

      // Add AI response
      const aiMessage: Message = {
        id: (Date.now() + 1).toString(),
        role: "assistant",
        content: data.response,
        symbol: data.symbol,
        liquidityData: hasLiquidityData ? data.data : undefined,
        showActions: hasLiquidityData, // Show Accept/Reject buttons if liquidity data exists
        ruleDraft,
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

  const patchDraft = (messageId: string, patch: Partial<DraftCard>) => {
    setMessages((prev) =>
      prev.map((m) =>
        m.id === messageId && m.ruleDraft ? { ...m, ruleDraft: { ...m.ruleDraft, ...patch } } : m,
      ),
    )
  }

  const handleArmDraft = async (messageId: string) => {
    const message = messages.find((m) => m.id === messageId)
    if (!message?.ruleDraft) return

    patchDraft(messageId, { status: "arming", error: undefined })
    try {
      await createRule(message.ruleDraft.draft)
      patchDraft(messageId, { status: "armed" })
      // The Strategy panel owns the Armed tab; tell it something changed.
      announceRulesChanged()
    } catch (err) {
      const text =
        err instanceof UnauthorizedError
          ? "Sign in with your wallet in the Strategy panel first, then arm this."
          : err instanceof Error
            ? err.message
            : "Could not arm this rule"
      patchDraft(messageId, { status: "pending", error: text })
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
      <div className="flex shrink-0 items-center justify-between gap-2 border-b border-border px-3 py-3 lg:px-4">
        <div className="flex min-w-0 items-center gap-2">
          <Sparkles className="h-4 w-4 shrink-0 text-primary" />
          <h2 className="text-sm font-semibold text-foreground">AI Assistant</h2>
        </div>
        <div className="flex shrink-0 items-center gap-2 lg:gap-3">
          <div className="flex items-center gap-2">
            <div className={`h-2 w-2 rounded-full ${isLoading ? "bg-yellow-500 animate-pulse" : "bg-green-500"}`} />
            <span className="text-xs text-muted-foreground">{isLoading ? "Thinking..." : "Online"}</span>
          </div>
          <Button onClick={onClose} size="icon" variant="ghost" className="h-9 w-9 lg:h-7 lg:w-7">
            <X className="h-4 w-4" />
          </Button>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-hidden">
        <ScrollArea className="h-full px-3 py-4 lg:px-4">
          <div className="space-y-4">
            {messages.map((message) => (
              <div key={message.id} className={`flex ${message.role === "user" ? "justify-end" : "justify-start"}`}>
                <div className={`max-w-[90%] sm:max-w-[85%] ${message.role === "user" ? "" : "w-full"}`}>
                  <div
                    className={`rounded-lg px-3 py-2.5 lg:px-4 ${
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

                  {/* A drafted alert rule. Arm is the only way it becomes real. */}
                  {message.role === "assistant" && message.ruleDraft && message.ruleDraft.status !== "dismissed" && (
                    <div className="mt-3 rounded-lg border border-border bg-card px-3 py-2.5">
                      <div className="flex items-center gap-2">
                        <Bell className="h-3.5 w-3.5 shrink-0 text-primary" />
                        <span className="text-xs font-medium text-foreground">
                          {message.ruleDraft.draft.name}
                        </span>
                        <span className="ml-auto font-mono text-[10px] text-muted-foreground">
                          {message.ruleDraft.draft.symbol} · {message.ruleDraft.draft.timeframe}
                        </span>
                      </div>
                      <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
                        {message.ruleDraft.summary}
                        {message.ruleDraft.draft.params.agent === "sequence" &&
                          ` · each step within ${message.ruleDraft.draft.params.within_bars} bars`}
                      </p>
                      {message.ruleDraft.error && (
                        <p className="mt-1.5 text-[11px] text-destructive">{message.ruleDraft.error}</p>
                      )}
                      {message.ruleDraft.status === "armed" ? (
                        <p className="mt-2 flex items-center gap-1 text-[11px] text-emerald-500">
                          <Check className="h-3 w-3" /> Armed — see the Strategy panel
                        </p>
                      ) : (
                        <div className="mt-2 flex gap-2">
                          <Button
                            size="sm"
                            onClick={() => handleArmDraft(message.id)}
                            disabled={message.ruleDraft.status === "arming"}
                            className="h-8 flex-1 text-xs"
                          >
                            {message.ruleDraft.status === "arming" ? (
                              <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
                            ) : (
                              <Bell className="mr-1 h-3.5 w-3.5" />
                            )}
                            Arm rule
                          </Button>
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => patchDraft(message.id, { status: "dismissed" })}
                            className="h-8 flex-1 text-xs"
                          >
                            Dismiss
                          </Button>
                        </div>
                      )}
                    </div>
                  )}

                  {/* Accept/Reject Buttons for Liquidity Levels */}
                  {message.role === "assistant" && message.showActions && message.liquidityData && (
                    <div className="mt-3 flex gap-2">
                      <Button
                        size="sm"
                        onClick={() => handleAcceptLevels(message.id)}
                        className="h-9 flex-1 bg-green-600 text-white hover:bg-green-700"
                      >
                        <Check className="h-4 w-4 mr-1" />
                        Mark on Chart
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => handleRejectLevels(message.id)}
                        className="h-9 flex-1 border-red-500/50 text-red-500 hover:bg-red-500/10"
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
      <div className="shrink-0 border-t border-border p-3 lg:p-4">
        <div className="flex gap-2">
          <Input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyPress={(e) => e.key === "Enter" && !e.shiftKey && handleSend()}
            placeholder="Ask about liquidity levels, strategies..."
            className="flex-1 bg-secondary border-border"
            disabled={isLoading}
          />
          <Button onClick={handleSend} size="icon" className="h-9 w-9 shrink-0" disabled={isLoading || !input.trim()}>
            {isLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
          </Button>
        </div>
        <p className="mt-2 text-xs text-muted-foreground">
          Try: "Show me liquidity levels for Bitcoin"
        </p>
        {/* The assistant writes in the register of advice, so the disclaimer
            belongs here rather than only in the footer of another page. */}
        <p className="mt-1.5 text-[11px] leading-relaxed text-muted-foreground/70">
          Analysis, not financial advice — and the assistant can be wrong.
          Decisions are yours.{" "}
          <a
            href="/legal/risk"
            target="_blank"
            rel="noopener noreferrer"
            className="underline underline-offset-2 hover:text-muted-foreground"
          >
            Risk disclosure
          </a>
        </p>
      </div>
    </div>
  )
}
