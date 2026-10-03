import {
  API_BASE,
  readError,
  type PatternScale,
  type PatternSource,
  type PatternState,
  type Strictness,
  type Timeframe,
} from "@/lib/api"
import { getToken } from "@/lib/session"

export type RuleAgent = "pattern" | "liquidity" | "sequence"
export type LevelSide = "support" | "resistance"
export type LevelEvent = "approach" | "break"
export type Strength = "weak" | "medium" | "strong"

export interface PatternRuleParams {
  agent: "pattern"
  kinds: ("W" | "M")[]
  states: PatternState[]
  min_confidence: number
  strictness: Strictness
  source: PatternSource
  scale: PatternScale
  lookback: number
}

export interface LiquidityRuleParams {
  agent: "liquidity"
  side: LevelSide
  min_strength: Strength
  event: LevelEvent
  proximity_pct: number
  lookback: number
}

/** Mirrors analysis/candles.py SHAPES. The server validates; this is for display. */
export type CandleShape =
  | "doji"
  | "hammer"
  | "shooting_star"
  | "bullish_engulfing"
  | "bearish_engulfing"
  | "inside_bar"

export interface CandleStep {
  type: "candle"
  shape: CandleShape
  max_body_pct?: number
}

export interface IndicatorStep {
  type: "indicator"
  indicator: "rsi"
  period: number
  cross: "above" | "below"
  level: number
}

export interface StructureStep {
  type: "structure"
  event: "breakout" | "sweep" | "rejection" | "pullback"
  side: "bullish" | "bearish"
}

export type SequenceStep = CandleStep | IndicatorStep | StructureStep

/** Steps in order, the last one landing on the newest closed bar. */
export interface SequenceRuleParams {
  agent: "sequence"
  steps: SequenceStep[]
  within_bars: number
  lookback?: number
}

export type RuleParams = PatternRuleParams | LiquidityRuleParams | SequenceRuleParams

/**
 * What the chat proposes after reading a sentence. Identical in shape to
 * CreateRuleInput on purpose: arming it is one createRule call, with nothing
 * for the client to reinterpret.
 */
export interface RuleDraft {
  name: string
  symbol: string
  timeframe: Timeframe
  params: RuleParams
  cooldown_secs: number
  persist_bars: number
}

/**
 * Fired by whoever creates a rule outside the Strategy panel (the chat), so
 * the panel's Armed tab can refetch without the two being wired together.
 */
export const RULES_CHANGED_EVENT = "vt:rules-changed"

export function announceRulesChanged(): void {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(RULES_CHANGED_EVENT))
  }
}

export interface Rule {
  id: string
  name: string
  agent: RuleAgent
  symbol: string
  timeframe: string
  params: Record<string, unknown>
  action: Record<string, unknown>
  enabled: boolean
  cooldown_secs: number
  persist_bars: number
  last_fired_at: string | null
  fire_count: number
  created_at: string
}

export interface RuleEvent {
  id: number
  rule_id: string
  rule_name: string | null
  symbol: string
  timeframe: string
  agent: RuleAgent
  direction: "bullish" | "bearish" | "neutral" | null
  price: number
  candle_time: string
  fired_at: string
  /** The signal can still repaint, so it may only ever alert. */
  provisional: boolean
  evidence: Record<string, any>
  action_kind: string
  action_status: string
}

/** Why a matched signal would still not fire. */
export type BlockedBy = "no_match" | "persistence" | "cooldown" | "dedup"

export interface RuleTestResult {
  would_fire: boolean
  blocked_by: BlockedBy | null
  signal: {
    agent: RuleAgent
    symbol: string
    timeframe: string
    candle_time: string
    identity: string
    direction: string
    price: number
    provisional: boolean
    evidence: Record<string, any>
  } | null
}

export interface CreateRuleInput {
  name: string
  symbol: string
  timeframe: Timeframe
  params: RuleParams
  cooldown_secs?: number
  persist_bars?: number
}

/**
 * The session is gone or was never established.
 *
 * Distinct from a general failure because the remedy is different: another
 * signature, not another attempt. The panel uses it to drop the stored token and
 * show the sign-in prompt again.
 */
export class UnauthorizedError extends Error {}

function headers(): HeadersInit {
  const token = getToken()
  if (!token) {
    // Fail here rather than send a request we know will 401.
    throw new UnauthorizedError("Sign in with your wallet to manage strategy rules")
  }
  return {
    "Content-Type": "application/json",
    Authorization: `Bearer ${token}`,
  }
}

async function fail(res: Response, fallback: string): Promise<never> {
  const message = await readError(res, fallback)
  throw res.status === 401 ? new UnauthorizedError(message) : new Error(message)
}

export async function listRules(symbol?: string): Promise<Rule[]> {
  const query = symbol ? `?symbol=${encodeURIComponent(symbol)}` : ""
  const res = await fetch(`${API_BASE}/api/rules${query}`, { headers: headers() })
  if (!res.ok) await fail(res, "Could not load rules")
  return res.json()
}

export async function createRule(input: CreateRuleInput): Promise<Rule> {
  const res = await fetch(`${API_BASE}/api/rules`, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify(input),
  })
  if (!res.ok) await fail(res, "Could not arm this rule")
  return res.json()
}

export async function updateRule(
  id: string,
  patch: { enabled?: boolean; name?: string },
): Promise<Rule> {
  const res = await fetch(`${API_BASE}/api/rules/${id}`, {
    method: "PATCH",
    headers: headers(),
    body: JSON.stringify(patch),
  })
  if (!res.ok) await fail(res, "Could not update this rule")
  return res.json()
}

export async function deleteRule(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/rules/${id}`, {
    method: "DELETE",
    headers: headers(),
  })
  if (!res.ok) await fail(res, "Could not delete this rule")
}

export async function testRule(id: string): Promise<RuleTestResult> {
  const res = await fetch(`${API_BASE}/api/rules/${id}/test`, {
    method: "POST",
    headers: headers(),
  })
  if (!res.ok) await fail(res, "Could not test this rule")
  return res.json()
}

export async function listEvents(limit = 50): Promise<RuleEvent[]> {
  const res = await fetch(`${API_BASE}/api/rules/events?limit=${limit}`, {
    headers: headers(),
  })
  if (!res.ok) await fail(res, "Could not load fired signals")
  return res.json()
}

/** Human-readable reason a rule that matched still did not fire. */
export const BLOCKED_REASON: Record<BlockedBy, string> = {
  no_match: "Conditions not met on the last closed candle",
  persistence: "Matched, but waiting for it to hold another candle",
  cooldown: "Matched, but still inside the cooldown window",
  dedup: "Already fired for this candle",
}
