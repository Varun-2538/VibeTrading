import { API_BASE } from "@/lib/api"
import { authHeaders, failResponse, type RuleParams } from "@/lib/rules"
import type { BarMark } from "@/lib/marks"

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
    // Absent on reports measured before a venue's directions were a question.
    sides?: Sides
    split: number
    bars: number
    warmup_bars: number
    from: number
    to: number
    split_time: number
    tape_cached: boolean
    replay_seconds: number
    exit?: ExitPlan
    // Absent on reports measured before the trade maths were versioned.
    parity_version?: number
  }
  signals: { fires: number; setups: number }
  study: { seen: PeriodStudy; unseen: PeriodStudy }
  trades?: { seen: TradePeriod; unseen: TradePeriod }
  tuning?: TuningReport
  flags?: string[]
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
  // A saved rule's id, when the backtest is being run for one. Sent as rule_id so
  // the report can later be named as the evidence that armed it; absent when the
  // rule is a draft nobody has saved.
  id?: string
  name: string
  symbol: string
  timeframe: string
  params: RuleParams | Record<string, unknown>
  cooldown_secs?: number
  persist_bars?: number
}

/**
 * Which directions a report measures. A spot pool cannot short - a position is
 * the asset or it is stablecoins - so a report meant as evidence for on-chain
 * execution has to be measured long-only, or it counted trades that pool could
 * never have taken.
 */
export type Sides = "both" | "long" | "short"

export const SIDES: { value: Sides; label: string }[] = [
  { value: "both", label: "Both" },
  { value: "long", label: "Long only" },
  { value: "short", label: "Short only" },
]

export async function createBacktest(
  rule: BacktestRule,
  options: { neutral: Neutral; sides: Sides; split: number; exit: ExitPlan; tune: boolean; grid?: Grid },
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
      rule_id: rule.id ?? null,
      neutral: options.neutral,
      sides: options.sides,
      split: options.split,
      exit: options.exit,
      tune: options.tune,
      grid: options.grid,
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


export interface ExitPlan {
  stop_atr: number | null
  stop_pct: number | null
  target_r: number | null
  target_pct: number | null
  max_bars: number
  exit_on_opposite: boolean
  fee_pct: number
  slippage_pct: number
  gas_usd: number
  trade_usd: number
  risk_pct: number
}

export const DEFAULT_EXIT: ExitPlan = {
  stop_atr: 1.5,
  stop_pct: null,
  target_r: 2,
  target_pct: null,
  max_bars: 20,
  exit_on_opposite: false,
  fee_pct: 0.05,
  slippage_pct: 0.02,
  gas_usd: 0,
  trade_usd: 1000,
  risk_pct: 1,
}

/**
 * The pool fee tiers a swap can route through, mirroring POOL_FEE_TIERS on the
 * server. The tier belongs to the pool the pair trades in, so it is picked, not
 * typed, and a round trip pays it twice.
 */
export const POOL_TIERS: { pct: number; what: string }[] = [
  { pct: 0.01, what: "stables" },
  { pct: 0.05, what: "majors" },
  { pct: 0.1, what: "majors" },
  { pct: 0.3, what: "most pairs" },
  { pct: 1, what: "thin pairs" },
]

/** Gas is a cost in dollars; only a position size turns it into a percent. */
export function gasPct(plan: ExitPlan): number {
  return plan.trade_usd > 0 ? (plan.gas_usd / plan.trade_usd) * 100 : 0
}

/** What a round trip costs before the chart moves at all: two swaps, two fills. */
export function roundTripPct(plan: ExitPlan): number {
  return 2 * (plan.fee_pct + gasPct(plan) + plan.slippage_pct)
}

/**
 * How far the stop must sit for the round trip to cost no more than `budgetR`
 * of risk. Costs in R are the round trip over the stop distance, so this is
 * that read backwards - and unlike a rule of thumb about ATR, it holds in any
 * regime and on any timeframe. BTC's hourly ATR was 0.25% of price the day this
 * shipped, which puts a 1.5-ATR stop at 0.37%: a 0.3% pool costs 1.7R a trade
 * there, and no signal survives that.
 */
export function stopPctForCostBudget(plan: ExitPlan, budgetR: number): number {
  return budgetR > 0 ? roundTripPct(plan) / budgetR : Infinity
}

export interface TradeRow {
  entry_time: number
  entry: number
  exit_time: number
  exit: number
  direction: "long" | "short"
  reason: "stop" | "target" | "time" | "opposite" | "end"
  r: number
  cost_r?: number
  pct: number
  bars: number
}

export interface TradePeriod {
  from: number
  to: number
  bars: number
  trades: number
  win_rate: number | null
  avg_win_r: number | null
  avg_loss_r: number | null
  expectancy_r: number | null
  // Absent on reports that finished before costs were measured per trade.
  gross_expectancy_r?: number | null
  cost_r?: number | null
  profit_factor: number | null
  total_return_pct: number | null
  max_drawdown_pct: number | null
  sharpe: number | null
  exposure_pct: number | null
  longest_losing_streak: number
  buy_hold_pct: number | null
  skipped_in_position: number
  skipped_neutral: number
  skipped_no_room: number
  skipped_side?: number
  equity: [number, number][]
  trade_list: TradeRow[]
  trades_listed: number
  flags: string[]
}

export const TIMEFRAME_MS: Record<string, number> = {
  "5m": 300_000,
  "15m": 900_000,
  "1h": 3_600_000,
  "1d": 86_400_000,
}

/** Candles the chart loads. A trade older than this cannot be drawn on it. */
export const CHART_BARS = 1000

export function fmtR(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—"
  return `${value > 0 ? "+" : ""}${value.toFixed(2)}R`
}

export function markable(trade: TradeRow, meta: { to: number; timeframe: string }): boolean {
  const step = TIMEFRAME_MS[meta.timeframe]
  if (!step) return false
  return trade.entry_time >= meta.to - (CHART_BARS - 10) * step
}

export function tradeMarks(trade: TradeRow): BarMark[] {
  const long = trade.direction === "long"
  return [
    { type: "bar", time: trade.entry_time, position: long ? "below" : "above", shape: long ? "arrowUp" : "arrowDown", text: long ? "Long" : "Short" },
    { type: "bar", time: trade.exit_time, position: long ? "above" : "below", shape: "circle", text: `${fmtR(trade.r)} ${trade.reason}` },
  ]
}

/** The page listens for this and draws the marks on the pair and timeframe they belong to. */
export const TRADE_MARKS_EVENT = "vt:trade-marks"

export interface TradeMarksDetail {
  symbol: string
  timeframe: string
  marks: BarMark[]
}

export function showTradesOnChart(detail: TradeMarksDetail): void {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent<TradeMarksDetail>(TRADE_MARKS_EVENT, { detail }))
  }
}

/**
 * SVG polyline points for the equity curve. Unseen continues from seen's final
 * equity, so the line is unbroken; x is proportional to time.
 */
export function equityLines(
  seen: [number, number][],
  unseen: [number, number][],
  width: number,
  height: number,
): { seen: string; unseen: string; boundaryX: number | null } {
  const carry = seen.length ? seen[seen.length - 1][1] : 1
  const points: [number, number][] = [...seen, ...unseen.map(([t, e]) => [t, e * carry] as [number, number])]
  if (points.length === 0) return { seen: "", unseen: "", boundaryX: null }

  const t0 = points[0][0]
  const t1 = points[points.length - 1][0]
  const values = points.map(([, e]) => e)
  const min = Math.min(...values)
  const span = Math.max(...values) - min || 1
  const x = (t: number) => (t1 === t0 ? 0 : ((t - t0) / (t1 - t0)) * width)
  const y = (e: number) => height - ((e - min) / span) * height
  const text = points.map(([t, e]) => `${x(t).toFixed(1)},${y(e).toFixed(1)}`)

  return {
    seen: text.slice(0, seen.length).join(" "),
    unseen: unseen.length ? text.slice(Math.max(0, seen.length - 1)).join(" ") : "",
    boundaryX: seen.length && unseen.length ? x(seen[seen.length - 1][0]) : null,
  }
}

export interface Grid {
  stop_atr: number[]
  target_r: number[]
  max_bars: number[]
  min_confidence: number[]
  min_strength: ("weak" | "medium" | "strong")[]
}

export const DEFAULT_GRID: Grid = {
  stop_atr: [1, 1.5, 2],
  target_r: [1, 2, 3],
  max_bars: [10, 20, 40],
  min_confidence: [60, 70, 80],
  min_strength: ["weak", "medium", "strong"],
}

export interface Setting {
  filters: { min_confidence?: number; min_strength?: string }
  stop_atr: number
  target_r: number
  max_bars: number
}

export interface TuningRow {
  settings: Setting
  trades: number
  expectancy_r: number | null
  max_drawdown_pct: number | null
  total_return_pct: number | null
}

export interface TuningReport {
  tried: number
  objective: string
  min_trades: number
  qualified: boolean
  chosen: Setting
  top: TuningRow[]
}

export function settingLabel(setting: Setting): string {
  const parts = [`stop ${setting.stop_atr} ATR`, `target ${setting.target_r}R`, `${setting.max_bars} bars`]
  if (setting.filters.min_confidence !== undefined) parts.push(`confidence ${setting.filters.min_confidence}`)
  if (setting.filters.min_strength !== undefined) parts.push(`strength ${setting.filters.min_strength}`)
  return parts.join(" · ")
}

export function overfit(report: BacktestReport): boolean {
  return (report.flags ?? []).includes("likely_overfit")
}

export function tradeVerdict(report: BacktestReport): string | null {
  if (!report.trades) return null
  const { seen, unseen } = report.trades
  if (unseen.trades === 0) return "No trades on unseen data."
  if (unseen.flags.includes("too_few_trades")) {
    return `Only ${unseen.trades} unseen trades — too few to judge this exit plan.`
  }
  const prefix = report.tuning ? `Selected from ${report.tuning.tried} settings: ` : "Trading it on unseen data: "
  const note = overfit(report) ? " — far below seen, so likely fitted to the seen data." : "."
  return (
    `${prefix}${fmtR(unseen.expectancy_r)} per trade over ${unseen.trades} unseen trades, ` +
    `${fmtPct(unseen.total_return_pct)} total, worst drawdown ${fmtPct(unseen.max_drawdown_pct)} ` +
    `(seen: ${fmtR(seen.expectancy_r)} per trade)${note}${costNote(unseen)}`
  )
}

/**
 * The line that separates a strategy with no edge from one whose edge went to
 * the pool. Both show a loss per trade; only the second is worth a wider stop
 * or a slower timeframe, where the same round trip is a smaller share of risk.
 */
export function costNote(unseen: TradePeriod): string {
  const net = unseen.expectancy_r ?? null
  const gross = unseen.gross_expectancy_r ?? null
  const cost = unseen.cost_r ?? null
  if (net === null || gross === null || cost === null || cost <= 0) return ""
  const paid = ` Costs took ${fmtR(-cost)} per trade: ${fmtR(gross)} before them, ${fmtR(net)} after.`
  if (gross > 0 && net <= 0) return `${paid} The signals earned an edge and the pool kept it.`
  return paid
}

export interface BacktestSummary {
  id: string
  /** The saved rule this was run for, when it was run for one. */
  rule_id?: string | null
  status: BacktestStatus
  progress: number
  created_at: string | null
  error: string | null
  request?: { rule?: { name?: string; symbol?: string; timeframe?: string } }
}

export async function listBacktests(): Promise<BacktestSummary[]> {
  const res = await fetch(`${API_BASE}/api/backtests`, { headers: authHeaders() })
  if (!res.ok) await failResponse(res, "Could not load your backtests")
  return res.json()
}
