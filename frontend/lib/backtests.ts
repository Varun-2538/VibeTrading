import { API_BASE } from "@/lib/api"
import { authHeaders, failResponse, type RuleParams } from "@/lib/rules"

export type BacktestStatus = "queued" | "replaying" | "studying" | "tuning" | "done" | "failed" | "cancelled"
export type Neutral = "skip" | "long" | "short"

export const ACTIVE_STATUSES: BacktestStatus[] = ["queued", "replaying", "studying", "tuning"]
export const BACKTEST_TIMEFRAMES = ["5m", "15m", "1h", "1d"] as const
export const HEADLINE_HORIZON = 10

export interface HorizonStudy {
  h: number
  signals: number
  mean_pct: number | null
  baseline_pct: number | null
  edge_pct: number | null
  ci_pct: [number, number] | null
  hit_rate: number | null
  baseline_hit_rate: number | null
}

export interface PeriodStudy {
  from: number | null
  to: number | null
  bars: number
  signals: number
  skipped_neutral: number
  long_share: number | null
  horizons: HorizonStudy[]
  mfe_atr: number | null
  mae_atr: number | null
  flags: string[]
}

export interface BacktestReport {
  meta: {
    symbol: string
    timeframe: string
    name: string
    neutral: Neutral
    split: number
    bars: number
    warmup_bars: number
    from: number
    to: number
    split_time: number
    tape_cached: boolean
    replay_seconds: number
  }
  signals: { fires: number; setups: number }
  study: { seen: PeriodStudy; unseen: PeriodStudy }
}

export interface Backtest {
  id: string
  status: BacktestStatus
  progress: number
  created_at: string | null
  started_at: string | null
  finished_at: string | null
  error: string | null
  report: BacktestReport | null
}

/** A rule as the Strategy panel lists it, or as the chat drafts it. */
export interface BacktestRule {
  name: string
  symbol: string
  timeframe: string
  params: RuleParams | Record<string, unknown>
  cooldown_secs?: number
  persist_bars?: number
}

export async function createBacktest(
  rule: BacktestRule,
  options: { neutral: Neutral; split: number },
): Promise<{ id: string; status: BacktestStatus }> {
  const res = await fetch(`${API_BASE}/api/backtests`, {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify({
      rule: {
        name: rule.name,
        symbol: rule.symbol,
        timeframe: rule.timeframe,
        params: rule.params,
        cooldown_secs: rule.cooldown_secs,
        persist_bars: rule.persist_bars,
      },
      neutral: options.neutral,
      split: options.split,
    }),
  })
  if (!res.ok) await failResponse(res, "Could not start the backtest")
  return res.json()
}

export async function getBacktest(id: string): Promise<Backtest> {
  const res = await fetch(`${API_BASE}/api/backtests/${id}`, { headers: authHeaders() })
  if (!res.ok) await failResponse(res, "Could not load the backtest")
  return res.json()
}

export async function cancelBacktest(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/backtests/${id}`, { method: "DELETE", headers: authHeaders() })
  if (!res.ok) await failResponse(res, "Could not cancel the backtest")
}

const DIRECTIONLESS = new Set(["doji", "inside_bar"])

/** Whether signals from this rule can have no direction, so the user must say how to read them. */
export function canBeNeutral(params: BacktestRule["params"]): boolean {
  const p = params as { agent?: string; steps?: { type?: string; shape?: string }[] }
  if (p.agent !== "sequence" || !p.steps?.length) return false
  const last = p.steps[p.steps.length - 1]
  return last.type === "candle" && DIRECTIONLESS.has(last.shape ?? "")
}

export function headline(period: PeriodStudy): HorizonStudy | undefined {
  return period.horizons.find((h) => h.h === HEADLINE_HORIZON)
}

export function fmtPct(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—"
  return `${value > 0 ? "+" : ""}${value.toFixed(2)}%`
}

/** One sentence on the unseen result, the only number that was not fitted to anything. */
export function verdict(report: BacktestReport): string {
  const unseen = report.study.unseen
  const h = headline(unseen)
  if (unseen.signals === 0 || !h) return "No signals on unseen data — nothing to judge."
  if (unseen.flags.includes("too_few_signals")) {
    return `Only ${unseen.signals} unseen signals — too few to judge.`
  }
  const ci = h.ci_pct ? ` (95% CI ${fmtPct(h.ci_pct[0])} to ${fmtPct(h.ci_pct[1])})` : ""
  if (unseen.flags.includes("no_edge_detected")) {
    return `No edge on unseen data: ${fmtPct(h.edge_pct)} per signal vs the market over ${HEADLINE_HORIZON} bars${ci}.`
  }
  return `Unseen edge ${fmtPct(h.edge_pct)} per signal over ${HEADLINE_HORIZON} bars${ci}, across ${unseen.signals} signals.`
}
