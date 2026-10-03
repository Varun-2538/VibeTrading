"use client"

/*
 * Strategy rules: build a condition, arm it, watch it fire.
 *
 * The engine runs server-side, so rules keep working with this tab closed and
 * the browser shut. What lands here is a notification of something that already
 * happened and is already recorded.
 *
 * Phase 1 rules can only raise an alert. Nothing here places a trade.
 */

import { useCallback, useEffect, useMemo, useState } from "react"
import { AlertCircle, Bell, Loader2, Plus, Trash2, Zap } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { ScrollArea } from "@/components/ui/scroll-area"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { PATTERN_SCALES, STRICTNESS, type Timeframe } from "@/lib/api"
import {
  BLOCKED_REASON,
  createRule,
  deleteRule,
  listEvents,
  listRules,
  testRule,
  updateRule,
  type LevelEvent,
  type LevelSide,
  type Rule,
  type RuleAgent,
  type RuleEvent,
  type RuleParams,
  type Strength,
} from "@/lib/rules"
import { useStrategySocket } from "@/hooks/use-strategy-socket"
import { cn } from "@/lib/utils"

interface AnalysisPanelProps {
  symbol: string
  timeframe: Timeframe
}

type PatternKind = "W" | "M"

const FIELD = "h-7 text-xs"

function relativeTime(iso: string): string {
  const seconds = Math.round((Date.now() - new Date(iso).getTime()) / 1000)
  if (seconds < 60) return `${Math.max(seconds, 0)}s ago`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`
  if (seconds < 86_400) return `${Math.floor(seconds / 3600)}h ago`
  return `${Math.floor(seconds / 86_400)}d ago`
}

export default function AnalysisPanel({ symbol, timeframe }: AnalysisPanelProps) {
  const [rules, setRules] = useState<Rule[]>([])
  const [events, setEvents] = useState<RuleEvent[]>([])
  const [tab, setTab] = useState("build")
  const [unseen, setUnseen] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [testing, setTesting] = useState<string | null>(null)
  const [testResult, setTestResult] = useState<{ id: string; message: string } | null>(null)

  // Builder state. Symbol and timeframe come from the chart; everything else is
  // snapshotted into the rule so later chart fiddling cannot change its meaning.
  const [name, setName] = useState("")
  const [agent, setAgent] = useState<RuleAgent>("pattern")
  const [kind, setKind] = useState<PatternKind | "both">("both")
  const [confirmedOnly, setConfirmedOnly] = useState(true)
  const [minConfidence, setMinConfidence] = useState(70)
  const [strictness, setStrictness] = useState<(typeof STRICTNESS)[number]>("balanced")
  const [scale, setScale] = useState<(typeof PATTERN_SCALES)[number]>("swing")
  const [side, setSide] = useState<LevelSide>("support")
  const [levelEvent, setLevelEvent] = useState<LevelEvent>("approach")
  const [minStrength, setMinStrength] = useState<Strength>("medium")
  const [proximity, setProximity] = useState(0.3)

  const refresh = useCallback(async () => {
    try {
      const [nextRules, nextEvents] = await Promise.all([listRules(), listEvents(50)])
      setRules(nextRules)
      setEvents(nextEvents)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not reach the rules service")
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const handleSignal = useCallback(() => {
    // Refetch rather than trusting the pushed payload: the row is authoritative
    // and this also picks up fire counts on the rule itself.
    void refresh()
    setUnseen((n) => n + 1)
  }, [refresh])

  useStrategySocket(symbol, handleSignal, refresh)

  useEffect(() => {
    if (tab === "fired") setUnseen(0)
  }, [tab, events.length])

  const params = useMemo((): RuleParams => {
    if (agent === "pattern") {
      return {
        agent: "pattern",
        kinds: kind === "both" ? ["W", "M"] : [kind],
        states: confirmedOnly ? ["confirmed"] : ["confirmed", "forming"],
        min_confidence: minConfidence,
        strictness,
        source: "wick",
        scale,
        lookback: 500,
      }
    }
    return {
      agent: "liquidity",
      side,
      min_strength: minStrength,
      event: levelEvent,
      proximity_pct: proximity,
      lookback: 500,
    }
  }, [agent, kind, confirmedOnly, minConfidence, strictness, scale, side, minStrength, levelEvent, proximity])

  const defaultName = useMemo(() => {
    if (agent === "pattern") {
      const which = kind === "both" ? "W/M" : kind
      return `${symbol} ${which} ${confirmedOnly ? "confirmed" : "forming"}`
    }
    return `${symbol} ${side} ${levelEvent}`
  }, [agent, kind, confirmedOnly, symbol, side, levelEvent])

  async function handleArm() {
    setBusy(true)
    setError(null)
    try {
      await createRule({
        name: name.trim() || defaultName,
        symbol,
        timeframe,
        params,
        // A rule must hold for one further close before it counts, which is what
        // stops a pattern that repaints away from raising an alert.
        persist_bars: 1,
        cooldown_secs: 900,
      })
      setName("")
      await refresh()
      setTab("armed")
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not arm this rule")
    } finally {
      setBusy(false)
    }
  }

  async function handleToggle(rule: Rule, enabled: boolean) {
    setRules((prev) => prev.map((r) => (r.id === rule.id ? { ...r, enabled } : r)))
    try {
      await updateRule(rule.id, { enabled })
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not update this rule")
      await refresh()
    }
  }

  async function handleDelete(rule: Rule) {
    setRules((prev) => prev.filter((r) => r.id !== rule.id))
    try {
      await deleteRule(rule.id)
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not delete this rule")
      await refresh()
    }
  }

  async function handleTest(rule: Rule) {
    setTesting(rule.id)
    setTestResult(null)
    try {
      const result = await testRule(rule.id)
      const message = result.would_fire
        ? "Would fire now"
        : result.blocked_by
          ? BLOCKED_REASON[result.blocked_by]
          : "Conditions not met"
      setTestResult({ id: rule.id, message })
    } catch (err) {
      setTestResult({
        id: rule.id,
        message: err instanceof Error ? err.message : "Test failed",
      })
    } finally {
      setTesting(null)
    }
  }

  return (
    <div className="flex h-full w-full flex-col bg-card">
      <Tabs value={tab} onValueChange={setTab} className="flex min-h-0 flex-1 flex-col gap-0">
        <div className="flex shrink-0 items-center justify-between gap-2 border-b border-border px-3 py-2 lg:px-4">
          <div className="flex items-center gap-2">
            <h2 className="text-sm font-semibold text-foreground">Strategy</h2>
            <span className="font-mono text-[11px] text-muted-foreground">
              {symbol} · {timeframe}
            </span>
          </div>
          <TabsList className="h-7">
            <TabsTrigger value="build" className="h-5 px-2 text-xs">
              Build
            </TabsTrigger>
            <TabsTrigger value="armed" className="h-5 px-2 text-xs">
              Armed
              {rules.length > 0 && (
                <span className="ml-1 text-muted-foreground">{rules.length}</span>
              )}
            </TabsTrigger>
            <TabsTrigger value="fired" className="h-5 px-2 text-xs">
              Fired
              {unseen > 0 && (
                <span className="ml-1 rounded-full bg-primary px-1 text-[10px] text-primary-foreground">
                  {unseen}
                </span>
              )}
            </TabsTrigger>
          </TabsList>
        </div>

        {error && (
          <div className="flex shrink-0 items-center gap-2 border-b border-border bg-destructive/10 px-3 py-1.5 text-xs text-destructive lg:px-4">
            <AlertCircle className="h-3.5 w-3.5 shrink-0" />
            <span className="truncate">{error}</span>
          </div>
        )}

        {/* Build ------------------------------------------------------------ */}
        <TabsContent value="build" className="mt-0 min-h-0 flex-1 overflow-y-auto px-3 py-3 lg:px-4">
          <div className="flex flex-wrap items-end gap-2">
            <div className="flex flex-col gap-1">
              <label className="text-[10px] uppercase tracking-wide text-muted-foreground">
                Agent
              </label>
              <Select value={agent} onValueChange={(v) => setAgent(v as RuleAgent)}>
                <SelectTrigger className={cn(FIELD, "w-[110px]")}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="pattern">Pattern</SelectItem>
                  <SelectItem value="liquidity">Liquidity</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {agent === "pattern" ? (
              <>
                <div className="flex flex-col gap-1">
                  <label className="text-[10px] uppercase tracking-wide text-muted-foreground">
                    Shape
                  </label>
                  <Select value={kind} onValueChange={(v) => setKind(v as PatternKind | "both")}>
                    <SelectTrigger className={cn(FIELD, "w-[110px]")}>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="both">W or M</SelectItem>
                      <SelectItem value="W">W (bottom)</SelectItem>
                      <SelectItem value="M">M (top)</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                <div className="flex flex-col gap-1">
                  <label className="text-[10px] uppercase tracking-wide text-muted-foreground">
                    Confidence ≥
                  </label>
                  <Input
                    type="number"
                    min={0}
                    max={100}
                    value={minConfidence}
                    onChange={(e) => setMinConfidence(Number(e.target.value))}
                    className={cn(FIELD, "w-[70px]")}
                  />
                </div>

                <div className="flex flex-col gap-1">
                  <label className="text-[10px] uppercase tracking-wide text-muted-foreground">
                    Strictness
                  </label>
                  <Select
                    value={strictness}
                    onValueChange={(v) => setStrictness(v as typeof strictness)}
                  >
                    <SelectTrigger className={cn(FIELD, "w-[100px]")}>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {STRICTNESS.map((s) => (
                        <SelectItem key={s} value={s}>
                          {s}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                <div className="flex flex-col gap-1">
                  <label className="text-[10px] uppercase tracking-wide text-muted-foreground">
                    Scale
                  </label>
                  <Select value={scale} onValueChange={(v) => setScale(v as typeof scale)}>
                    <SelectTrigger className={cn(FIELD, "w-[90px]")}>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {PATTERN_SCALES.map((s) => (
                        <SelectItem key={s} value={s}>
                          {s}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                <label className="flex h-7 items-center gap-2 text-xs text-muted-foreground">
                  <Switch checked={confirmedOnly} onCheckedChange={setConfirmedOnly} />
                  Confirmed only
                </label>
              </>
            ) : (
              <>
                <div className="flex flex-col gap-1">
                  <label className="text-[10px] uppercase tracking-wide text-muted-foreground">
                    Level
                  </label>
                  <Select value={side} onValueChange={(v) => setSide(v as LevelSide)}>
                    <SelectTrigger className={cn(FIELD, "w-[110px]")}>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="support">Support</SelectItem>
                      <SelectItem value="resistance">Resistance</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                <div className="flex flex-col gap-1">
                  <label className="text-[10px] uppercase tracking-wide text-muted-foreground">
                    Event
                  </label>
                  <Select
                    value={levelEvent}
                    onValueChange={(v) => setLevelEvent(v as LevelEvent)}
                  >
                    <SelectTrigger className={cn(FIELD, "w-[110px]")}>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="approach">Approaches</SelectItem>
                      <SelectItem value="break">Breaks</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                <div className="flex flex-col gap-1">
                  <label className="text-[10px] uppercase tracking-wide text-muted-foreground">
                    Strength ≥
                  </label>
                  <Select
                    value={minStrength}
                    onValueChange={(v) => setMinStrength(v as Strength)}
                  >
                    <SelectTrigger className={cn(FIELD, "w-[95px]")}>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="weak">weak</SelectItem>
                      <SelectItem value="medium">medium</SelectItem>
                      <SelectItem value="strong">strong</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                {levelEvent === "approach" && (
                  <div className="flex flex-col gap-1">
                    <label className="text-[10px] uppercase tracking-wide text-muted-foreground">
                      Within %
                    </label>
                    <Input
                      type="number"
                      min={0.01}
                      step={0.1}
                      value={proximity}
                      onChange={(e) => setProximity(Number(e.target.value))}
                      className={cn(FIELD, "w-[70px]")}
                    />
                  </div>
                )}
              </>
            )}

            <div className="flex flex-col gap-1">
              <label className="text-[10px] uppercase tracking-wide text-muted-foreground">
                Name
              </label>
              <Input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder={defaultName}
                className={cn(FIELD, "w-[190px]")}
              />
            </div>

            <Button onClick={handleArm} disabled={busy} size="sm" className="h-7 gap-1 text-xs">
              {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />}
              Arm rule
            </Button>
          </div>

          <p className="mt-3 max-w-2xl text-[11px] leading-relaxed text-muted-foreground">
            Rules are evaluated server-side on closed candles only, and must hold for one
            further candle before firing — so a pattern that repaints away never alerts.
            Alerts only; nothing here places a trade. Rules are tied to this browser.
          </p>
        </TabsContent>

        {/* Armed ------------------------------------------------------------ */}
        <TabsContent value="armed" className="mt-0 min-h-0 flex-1">
          {rules.length === 0 ? (
            <div className="flex h-full items-center justify-center px-6 text-center">
              <p className="text-xs text-muted-foreground">
                No rules yet. Build one to get alerted when your conditions are met.
              </p>
            </div>
          ) : (
            <ScrollArea className="h-full">
              <div className="divide-y divide-border">
                {rules.map((rule) => (
                  <div key={rule.id} className="flex items-center gap-3 px-3 py-2 lg:px-4">
                    <Switch
                      checked={rule.enabled}
                      onCheckedChange={(v) => handleToggle(rule, v)}
                      aria-label={`Enable ${rule.name}`}
                    />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-1.5">
                        <span className="truncate text-xs font-medium text-foreground">
                          {rule.name}
                        </span>
                        <Badge variant="secondary" className="h-4 px-1 text-[10px]">
                          {rule.agent}
                        </Badge>
                        <span className="font-mono text-[10px] text-muted-foreground">
                          {rule.symbol} {rule.timeframe}
                        </span>
                      </div>
                      <p className="mt-0.5 text-[10px] text-muted-foreground">
                        {rule.fire_count > 0 && rule.last_fired_at
                          ? `Fired ${rule.fire_count}× · last ${relativeTime(rule.last_fired_at)}`
                          : "Not fired yet"}
                        {testResult?.id === rule.id && ` · ${testResult.message}`}
                      </p>
                    </div>
                    <Button
                      onClick={() => handleTest(rule)}
                      disabled={testing === rule.id}
                      variant="ghost"
                      size="sm"
                      className="h-6 gap-1 px-2 text-[11px]"
                    >
                      {testing === rule.id ? (
                        <Loader2 className="h-3 w-3 animate-spin" />
                      ) : (
                        <Zap className="h-3 w-3" />
                      )}
                      Test
                    </Button>
                    <Button
                      onClick={() => handleDelete(rule)}
                      variant="ghost"
                      size="sm"
                      className="h-6 w-6 p-0 text-muted-foreground hover:text-destructive"
                      aria-label={`Delete ${rule.name}`}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                ))}
              </div>
            </ScrollArea>
          )}
        </TabsContent>

        {/* Fired ------------------------------------------------------------ */}
        <TabsContent value="fired" className="mt-0 min-h-0 flex-1">
          {events.length === 0 ? (
            <div className="flex h-full items-center justify-center px-6 text-center">
              <p className="text-xs text-muted-foreground">
                Nothing has fired yet. Armed rules are checked every minute.
              </p>
            </div>
          ) : (
            <ScrollArea className="h-full">
              <div className="divide-y divide-border">
                {events.map((event) => (
                  <div
                    key={event.id}
                    className={cn(
                      "flex items-center gap-3 px-3 py-2 lg:px-4",
                      // A provisional signal can still repaint, so it reads as
                      // weaker than a confirmed one.
                      event.provisional && "opacity-60",
                    )}
                  >
                    <Bell
                      className={cn(
                        "h-3.5 w-3.5 shrink-0",
                        event.direction === "bullish" ? "text-emerald-500" : "text-red-500",
                      )}
                    />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-1.5">
                        <span className="truncate text-xs font-medium text-foreground">
                          {event.rule_name ?? "Rule"}
                        </span>
                        {event.provisional && (
                          <Badge variant="outline" className="h-4 px-1 text-[10px]">
                            forming
                          </Badge>
                        )}
                        <span className="font-mono text-[10px] text-muted-foreground">
                          {event.symbol} {event.timeframe}
                        </span>
                      </div>
                      <p className="mt-0.5 truncate text-[10px] text-muted-foreground">
                        {event.direction} at{" "}
                        <span className="font-mono">{Number(event.price).toLocaleString()}</span>
                        {event.evidence?.strength && ` · ${event.evidence.strength} level`}
                        {event.evidence?.kind && ` · ${event.evidence.kind} ${event.evidence.state}`}
                        {event.evidence?.confidence != null &&
                          ` · ${event.evidence.confidence}% confidence`}
                      </p>
                    </div>
                    <span className="shrink-0 text-[10px] text-muted-foreground">
                      {relativeTime(event.fired_at)}
                    </span>
                  </div>
                ))}
              </div>
            </ScrollArea>
          )}
        </TabsContent>
      </Tabs>
    </div>
  )
}
