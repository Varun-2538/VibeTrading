/**
 * The execution API: an account's rails, which rules may trade, and what happened.
 *
 * Nothing here places a trade. Arming is a decision the server records after a
 * backtest has passed, and the caps are ceilings the owner sets on themselves. The
 * trading itself happens inside a vault the owner deployed, against a permission
 * they can revoke on-chain without asking us.
 */
import { authHeaders, failResponse } from "@/lib/rules"

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"

export type ExecutionMode = "off" | "shadow" | "live"

export interface ExecutionAccount {
  owner_key: string
  configured: boolean
  mode: ExecutionMode
  kill_switch: boolean
  equity_usd: number
  max_notional_usd: number
  max_concurrent_positions: number
  max_trades_per_day: number
  daily_loss_limit_usd: number
  halted_reason: string | null
  execution_enabled: boolean
  parity_version: number
  /** The address a vault owner grants to. Null until an executor key exists. */
  operator_address: string | null
  /** Where vaults can live, published by the server. Absent from an older backend. */
  chains?: ExecutionChain[]
}

/** One chain vaults can be deployed on, as GET /account publishes it. */
export interface ExecutionChain {
  key: "arbitrum" | "robinhood"
  chain_id: number
  name: string
  venue: string
  stable: string
  stable_symbol: string
  /** Null until the factory is deployed on this chain. */
  factory: string | null
  /** Market name to the token a position is held in. */
  markets: Record<string, string>
  /** Markets whose feed follows US market hours: vaultable, not yet armable. */
  stock_markets?: string[]
  explorer: string
}

export interface AccountSettings {
  mode: ExecutionMode
  equity_usd: number
  max_notional_usd: number
  max_concurrent_positions: number
  max_trades_per_day: number
  daily_loss_limit_usd: number
}

export interface PreflightResult {
  passed: boolean
  reasons: string[]
  evidence: Record<string, unknown>
  /** Failed on quality alone: the owner may arm it anyway, having read why. */
  overridable?: boolean
  /** On an armed policy: it was armed against this advice. */
  overridden?: boolean
  overridden_at?: string
}

export interface ArmedPolicy {
  rule_id: string
  armed: boolean
  venue: string
  market: string
  parity_version: number
  parity_current: boolean
  backtest_job_id: string | null
  preflight: PreflightResult | null
  armed_at: string | null
  disarmed_reason: string | null
  exit?: Record<string, unknown>
  policy?: Record<string, unknown>
}

export interface ExecutionPosition {
  id: string
  rule_id: string
  status: "opening" | "open" | "closing" | "closed" | "abandoned"
  mode: "shadow" | "live"
  venue: string
  market: string
  symbol: string
  timeframe: string
  direction: "long" | "short"
  entry_price: number | null
  qty: number | null
  notional_usd: number | null
  stop_price: number | null
  target_price: number | null
  deadline: string | null
  opened_at: string | null
  closed_at: string | null
  exit_price: number | null
  exit_reason: string | null
  realised_pnl_usd: number | null
  realised_r: number | null
  reference: Record<string, unknown> | null
}

export interface ExecutionHealth {
  execution_enabled: boolean
  globally_halted: string | null
  mode: ExecutionMode
  kill_switch: boolean
  halted_reason: string | null
  parity_version: number
  queued: number
  stuck_intents: number
  orders_in_doubt: number
  open_positions: number
}

export const MARKETS = ["WETH/USDC", "WBTC/USDC", "WETH/USDG"] as const
export type Market = (typeof MARKETS)[number]

/** Which chain a market is on. The quote token decides: USDC is Arbitrum One's, USDG Robinhood Chain's. */
export const MARKET_CHAIN: Record<Market, { key: ExecutionChain["key"]; name: string; stable: string }> = {
  "WETH/USDC": { key: "arbitrum", name: "Arbitrum One", stable: "USDC" },
  "WBTC/USDC": { key: "arbitrum", name: "Arbitrum One", stable: "USDC" },
  "WETH/USDG": { key: "robinhood", name: "Robinhood Chain", stable: "USDG" },
}

/**
 * Every market a rule could trade in, from the symbol it watches - one per chain
 * that has a pool for it, Robinhood Chain first where it has one.
 *
 * Empty for everything else, and that is most of the pairs the app charts. A vault
 * needs a deep Uniswap pool and a Chainlink feed, and only two of the nine coins have
 * both - so a rule on SOL can alert all it likes and can never be armed to trade.
 */
export function marketsForSymbol(symbol: string): Market[] {
  const upper = (symbol || "").toUpperCase()
  if (upper.startsWith("ETH")) return ["WETH/USDG", "WETH/USDC"]
  if (upper.startsWith("BTC")) return ["WBTC/USDC"]
  return []
}

/** The first market for a symbol, or null when it has none. */
export function marketForSymbol(symbol: string): Market | null {
  return marketsForSymbol(symbol)[0] ?? null
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}/api/execution${path}`, { headers: authHeaders(), ...init })
  if (!res.ok) await failResponse(res, "The execution service refused that")
  return res.json()
}

export async function getAccount(): Promise<ExecutionAccount> {
  return call<ExecutionAccount>("/account")
}

export async function saveAccount(settings: AccountSettings): Promise<ExecutionAccount> {
  return call<ExecutionAccount>("/account", { method: "PUT", body: JSON.stringify(settings) })
}

export async function setKillSwitch(on: boolean): Promise<ExecutionAccount> {
  return call<ExecutionAccount>("/kill", { method: on ? "POST" : "DELETE" })
}

export async function listPolicies(): Promise<ArmedPolicy[]> {
  return call<ArmedPolicy[]>("/policies")
}

export async function listPositions(): Promise<ExecutionPosition[]> {
  return call<ExecutionPosition[]>("/positions")
}

export async function getHealth(): Promise<ExecutionHealth> {
  return call<ExecutionHealth>("/health")
}

export interface ArmRequest {
  market: Market
  backtest_job_id: string
  exit: Record<string, unknown>
  neutral?: "skip" | "long" | "short"
  max_notional_usd?: number
  thresholds?: { min_expectancy_r?: number; max_drawdown_pct?: number }
  /** Arm despite a quality failure. The server refuses it for anything else. */
  override?: boolean
}

function armBody(request: ArmRequest) {
  return JSON.stringify({
    action: {
      kind: "dex_trade",
      market: request.market,
      exit: request.exit,
      neutral: request.neutral ?? "skip",
      max_notional_usd: request.max_notional_usd ?? 100,
    },
    backtest_job_id: request.backtest_job_id,
    thresholds: request.thresholds,
    override: request.override ?? false,
  })
}

/** Runs the gate and reports, without arming anything. */
export async function preflight(ruleId: string, request: ArmRequest): Promise<PreflightResult> {
  return call<PreflightResult>(`/rules/${ruleId}/preflight`, { method: "POST", body: armBody(request) })
}

export async function armRule(ruleId: string, request: ArmRequest): Promise<ArmedPolicy> {
  return call<ArmedPolicy>(`/rules/${ruleId}/arm`, { method: "POST", body: armBody(request) })
}

export async function disarmRule(ruleId: string): Promise<ArmedPolicy> {
  return call<ArmedPolicy>(`/rules/${ruleId}/arm`, { method: "DELETE" })
}

/**
 * What the panel says about an account in one line.
 *
 * "Armed" and "running" are different states and the difference is the most
 * confusing thing about this feature, so the sentence always says which one is
 * missing rather than reporting a mode and leaving the reader to work it out.
 */
export function accountSummary(account: ExecutionAccount | null): string {
  if (account === null) return "Sign in with your wallet to set up execution."
  if (account.halted_reason) return `Halted: ${account.halted_reason}. Nothing new will open.`
  if (account.kill_switch) return "Kill switch is on. Open positions can still close; nothing new will open."
  if (!account.execution_enabled) {
    return account.mode === "off"
      ? "Execution is switched off, here and on the server."
      : `Your account is in ${account.mode} mode, but execution is switched off on the server.`
  }
  if (account.mode === "off") return "Execution is running on the server; your account is off."
  if (account.mode === "shadow") return "Shadow mode: every trade is recorded and none is sent."
  return `Live, up to ${fmtUsd(account.max_notional_usd)} a trade and ${account.max_trades_per_day} trades a day.`
}

export function fmtUsd(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—"
  return `$${value.toLocaleString(undefined, { maximumFractionDigits: 2 })}`
}

export function fmtR(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—"
  return `${value > 0 ? "+" : ""}${value.toFixed(2)}R`
}

/** Whether anything is wrong, as opposed to nothing having happened yet. */
export function healthTrouble(health: ExecutionHealth | null): string | null {
  if (health === null) return null
  if (health.globally_halted) return `Execution is halted server-wide: ${health.globally_halted}`
  if (health.halted_reason) return `This account is halted: ${health.halted_reason}`
  if (health.orders_in_doubt > 0) {
    return `${health.orders_in_doubt} order(s) whose outcome is unknown — waiting for reconciliation.`
  }
  if (health.stuck_intents > 0) return `${health.stuck_intents} intent(s) claimed but unfinished.`
  return null
}

/**
 * The preflight's refusals, ready to render. Every reason, never the first: someone
 * fixing them one at a time learns nothing about the rest.
 */
export function refusalLines(result: PreflightResult | null): string[] {
  return result && !result.passed ? result.reasons : []
}
