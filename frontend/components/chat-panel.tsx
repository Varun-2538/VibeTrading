"use client"

import { useEffect, useMemo, useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Send, Sparkles, X, Loader2, Check, XIcon, Bell, Eye, EyeOff, MapPin } from "lucide-react"
import { API_BASE, type Timeframe } from "@/lib/api"
import { markKey, type ChatTurn, type FellowAnswer, type Mark, type PatternSettings, type Viewport } from "@/lib/marks"
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
  /** The chart fellow's structured answer: what it saw, and what it could draw. */
  fellow?: FellowAnswer
}

interface ChatPanelProps {
  onClose: () => void
  currentSymbol?: string
  onSymbolChange?: (symbol: string) => void
  onMarkLevels?: (data: { symbol: string; liquidityData: LiquidityData }) => void
  /** The chart's timeframe, window and detector settings: what "the chart" means right now. */
  timeframe?: Timeframe
  viewport?: Viewport | null
  patternSettings?: PatternSettings
  /** Marks the user toggled on, for the chart to draw. */
  onMarks?: (marks: Mark[]) => void
}

/** The last few exchanges, trimmed. Sent with each question; never stored. */
const HISTORY_TURNS = 8
const HISTORY_CHARS = 300

export default function ChatPanel({
  onClose,
  currentSymbol,
  onSymbolChange,
  onMarkLevels,
  timeframe = "1h",
  viewport,
  patternSettings,
  onMarks,
}: ChatPanelProps) {
  const [messages, setMessages] = useState<Message[]>([
    {
      id: "1",
      role: "assistant",
      content:
        "I'm looking at the same chart you are. Ask what you'd ask a trader next to you: do you see support here, a double bottom, a doji, an RSI cross? I'll say what I see and what I don't, and mark it on the chart if you want.\n\nFor alerts: \"alert me when a doji forms and RSI(14) crosses above 30\".\n\nAvailable: BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT, XRPUSDT, ADAUSDT, DOGEUSDT, DOTUSDT, AVAXUSDT",
    },
  ])
  const [input, setInput] = useState("")
  const [isLoading, setIsLoading] = useState(false)
  // Which findings are drawn, by mark key. Reset when the chart moves to a
  // different symbol or timeframe, because the chart clears its drawings then.
  const [marked, setMarked] = useState<Map<string, Mark>>(new Map())

  useEffect(() => {
    setMarked(new Map())
  }, [currentSymbol, timeframe])

  useEffect(() => {
    onMarks?.(Array.from(marked.values()))
  }, [marked, onMarks])

  const history = useMemo((): ChatTurn[] => {
    return messages
      .filter((m) => m.id !== "1")
      .slice(-HISTORY_TURNS)
      .map((m) => ({ role: m.role, content: m.content.slice(0, HISTORY_CHARS) }))
  }, [messages])

  const toggleFinding = (marks: Mark[]) => {
    setMarked((prev) => {
      const next = new Map(prev)
      const keys = marks.map(markKey)
      const allOn = keys.every((k) => next.has(k))
      keys.forEach((key, i) => {
        if (allOn) next.delete(key)
        else next.set(key, marks[i])
      })
      return next
    })
  }

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
          timeframe,
          // What is on screen. With this present, the server answers from the
          // detectors' view of exactly these candles.
          window: viewport ?? undefined,
          pattern_settings: patternSettings,
          history,
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
        fellow: data.data?.fellow ?? undefined,
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
        content: "I couldn't reach the analysis service just now. Try again in a moment.",
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

                  {/* What the fellow saw, one line per thing asked, each drawable. */}
                  {message.role === "assistant" && message.fellow && message.fellow.findings.length > 0 && (
                    <div className="mt-2 space-y-1">
                      {message.fellow.findings.map((f, i) => {
                        const keys = f.marks.map(markKey)
                        const on = keys.length > 0 && keys.every((k) => marked.has(k))
                        return (
                          <div
                            key={i}
                            className="flex items-start gap-2 rounded-md border border-border bg-card px-2.5 py-1.5"
                          >
                            {f.present ? (
                              <Eye className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-500" />
                            ) : (
                              <EyeOff className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                            )}
                            <div className="min-w-0 flex-1">
                              <div className="flex items-center gap-1.5 text-xs">
                                <span className={f.present ? "font-medium text-foreground" : "text-muted-foreground"}>
                                  {f.label}
                                </span>
                                {f.present && f.confidence > 0 && (
                                  <span className="font-mono text-[10px] text-muted-foreground">
                                    {Math.round(f.confidence)}%
                                  </span>
                                )}
                                {!f.grounded && (
                                  <span
                                    className="text-[10px] text-amber-500"
                                    title="Some marks were dropped: the detectors did not find them on this window."
                                  >
                                    unverified
                                  </span>
                                )}
                              </div>
                              {f.why && <p className="text-[11px] leading-snug text-muted-foreground">{f.why}</p>}
                            </div>
                            {f.present && f.marks.length > 0 && (
                              <Button
                                size="sm"
                                variant={on ? "default" : "outline"}
                                onClick={() => toggleFinding(f.marks)}
                                className="h-6 shrink-0 gap-1 px-2 text-[11px]"
                                aria-pressed={on}
                              >
                                <MapPin className="h-3 w-3" />
                                {on ? "Marked" : "Mark"}
                              </Button>
                            )}
                          </div>
                        )
                      })}
                      {message.fellow.not_visible.length > 0 && (
                        <p className="px-1 text-[11px] text-muted-foreground">
                          Can&apos;t see yet: {message.fellow.not_visible.join(", ").replace(/_/g, " ")}
                        </p>
                      )}
                      {message.fellow.findings.some((f) => f.present && f.marks.length > 0) && (
                        <button
                          onClick={() => {
                            const all = message.fellow?.findings.filter((f) => f.present).flatMap((f) => f.marks) ?? []
                            toggleFinding(all)
                          }}
                          className="px-1 text-[11px] text-primary underline-offset-2 hover:underline"
                        >
                          Mark everything it sees
                        </button>
                      )}
                    </div>
                  )}

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
          Try: "do you see support or a double bottom forming here?"
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
