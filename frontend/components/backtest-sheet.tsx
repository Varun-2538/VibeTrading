"use client"

import { useEffect, useState } from "react"
import { FlaskConical, Loader2, MapPin } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Progress } from "@/components/ui/progress"
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import {
  ACTIVE_STATUSES,
  BACKTEST_TIMEFRAMES,
  DEFAULT_EXIT,
  canBeNeutral,
  cancelBacktest,
  createBacktest,
  DEFAULT_GRID,
  equityLines,
  fmtPct,
  fmtR,
  gasPct,
  stopPctForCostBudget,
  getBacktest,
  markable,
  overfit,
  POOL_TIERS,
  roundTripPct,
  settingLabel,
  SIDES,
  showTradesOnChart,
  tradeMarks,
  tradeVerdict,
  verdict,
  type Backtest,
  type BacktestReport,
  type BacktestRule,
  type ExitPlan,
  type Neutral,
  type Sides,
  type PeriodStudy,
  type TradePeriod,
  type TradeRow,
  type TuningReport,
} from "@/lib/backtests"
import { UnauthorizedError } from "@/lib/rules"
import { cn } from "@/lib/utils"

const POLL_MS = 3000
// The share of risk it is still worth paying to trade. Past this the costs, not
// the signal, are what the report measures.
const COST_BUDGET_R = 0.2
const SPLITS = [0.6, 0.7, 0.8]
const LISTED = 50
const STAGE: Record<string, string> = {
  queued: "Waiting for the worker",
  replaying: "Replaying history bar by bar",
  studying: "Measuring what followed each signal",
  tuning: "Tuning on seen data",
}

function day(ms: number | null) {
  return ms === null ? "—" : new Date(ms).toISOString().slice(0, 10)
}

function StudyTable({ title, period }: { title: string; period: PeriodStudy }) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between">
        <h3 className="text-xs font-semibold text-foreground">{title}</h3>
        <span className="font-mono text-[10px] text-muted-foreground">
          {day(period.from)} → {day(period.to)} · {period.signals} signals
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-[11px]">
          <thead className="text-muted-foreground">
            <tr className="text-left">
              <th className="py-1 pr-2 font-normal">After</th>
              <th className="py-1 pr-2 font-normal">Signal</th>
              <th className="py-1 pr-2 font-normal">Market</th>
              <th className="py-1 pr-2 font-normal">Edge</th>
              <th className="py-1 pr-2 font-normal">95% CI</th>
              <th className="py-1 font-normal">Hit</th>
            </tr>
          </thead>
          <tbody className="font-mono">
            {period.horizons.map((h) => (
              <tr key={h.h} className="border-t border-border">
                <td className="py-1 pr-2">{h.h} bars</td>
                <td className="py-1 pr-2">{fmtPct(h.mean_pct)}</td>
                <td className="py-1 pr-2 text-muted-foreground">{fmtPct(h.baseline_pct)}</td>
                <td className={cn("py-1 pr-2", (h.edge_pct ?? 0) > 0 ? "text-emerald-500" : "text-red-400")}>
                  {fmtPct(h.edge_pct)}
                </td>
                <td className="py-1 pr-2 text-muted-foreground">
                  {h.ci_pct ? `${fmtPct(h.ci_pct[0])} … ${fmtPct(h.ci_pct[1])}` : "—"}
                </td>
                <td className="py-1">{h.hit_rate === null ? "—" : `${Math.round(h.hit_rate * 100)}%`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-[10px] text-muted-foreground">
        Moved for it {period.mfe_atr?.toFixed(2) ?? "—"} ATR, against it {period.mae_atr?.toFixed(2) ?? "—"} ATR
        within 20 bars
        {period.skipped_neutral > 0 && ` · ${period.skipped_neutral} directionless signals skipped`}
        {(period.skipped_side ?? 0) > 0 && ` · ${period.skipped_side} in a direction this venue cannot take`}
        {period.flags.includes("too_few_signals") && " · too few signals to judge"}
      </p>
    </div>
  )
}

function NumberField({
  label,
  value,
  step,
  onChange,
}: {
  label: string
  value: number | null
  step: number
  onChange: (value: number) => void
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[10px] text-muted-foreground">{label}</span>
      <Input
        type="number"
        inputMode="decimal"
        step={step}
        min={0}
        value={value ?? ""}
        onChange={(e) => onChange(Number(e.target.value))}
        className="h-7 px-2 font-mono text-xs"
      />
    </label>
  )
}

const METRICS: { label: string; get: (p: TradePeriod) => string }[] = [
  { label: "Trades", get: (p) => String(p.trades) },
  { label: "Win rate", get: (p) => (p.win_rate === null ? "—" : `${Math.round(p.win_rate * 100)}%`) },
  { label: "Per trade", get: (p) => fmtR(p.expectancy_r) },
  { label: "Before costs", get: (p) => fmtR(p.gross_expectancy_r) },
  { label: "Costs took", get: (p) => (p.cost_r === null || p.cost_r === undefined ? "—" : fmtR(-p.cost_r)) },
  { label: "Avg win / loss", get: (p) => `${fmtR(p.avg_win_r)} / ${fmtR(p.avg_loss_r)}` },
  { label: "Profit factor", get: (p) => p.profit_factor?.toFixed(2) ?? "—" },
  { label: "Return", get: (p) => fmtPct(p.total_return_pct) },
  { label: "Max drawdown", get: (p) => fmtPct(p.max_drawdown_pct) },
  { label: "Sharpe", get: (p) => p.sharpe?.toFixed(2) ?? "—" },
  { label: "Time in market", get: (p) => (p.exposure_pct === null ? "—" : `${Math.round(p.exposure_pct)}%`) },
  { label: "Longest losing run", get: (p) => String(p.longest_losing_streak) },
  { label: "Buy & hold", get: (p) => fmtPct(p.buy_hold_pct) },
]

function MetricsTable({ seen, unseen }: { seen: TradePeriod; unseen: TradePeriod }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[11px]">
        <thead className="text-muted-foreground">
          <tr className="text-left">
            <th className="py-1 pr-2 font-normal" />
            <th className="py-1 pr-2 font-normal">Unseen</th>
            <th className="py-1 font-normal">Seen</th>
          </tr>
        </thead>
        <tbody className="font-mono">
          {METRICS.map((m) => (
            <tr key={m.label} className="border-t border-border">
              <td className="py-1 pr-2 font-sans text-muted-foreground">{m.label}</td>
              <td className="py-1 pr-2">{m.get(unseen)}</td>
              <td className="py-1">{m.get(seen)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function EquityChart({ seen, unseen }: { seen: TradePeriod; unseen: TradePeriod }) {
  const width = 300
  const height = 80
  const lines = equityLines(seen.equity, unseen.equity, width, height)
  return (
    <div className="space-y-1">
      <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" className="h-20 w-full" aria-label="Equity curve, seen then unseen">
        {lines.boundaryX !== null && (
          <line x1={lines.boundaryX} x2={lines.boundaryX} y1={0} y2={height} className="stroke-border" strokeDasharray="3 3" vectorEffect="non-scaling-stroke" />
        )}
        <polyline points={lines.seen} fill="none" className="stroke-muted-foreground" strokeWidth={1.2} vectorEffect="non-scaling-stroke" />
        <polyline points={lines.unseen} fill="none" className="stroke-primary" strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
      </svg>
      <div className="flex justify-between font-mono text-[10px] text-muted-foreground">
        <span>seen</span>
        <span>unseen →</span>
      </div>
    </div>
  )
}

function TradeList({
  period,
  meta,
  onMark,
}: {
  period: TradePeriod
  meta: BacktestReport["meta"]
  onMark: (trades: TradeRow[]) => void
}) {
  const rows = period.trade_list.slice(-LISTED).reverse()
  const recent = period.trade_list.filter((t) => markable(t, meta)).slice(-LISTED)
  if (rows.length === 0) return <p className="text-[11px] text-muted-foreground">No trades in this period.</p>
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[10px] text-muted-foreground">
          Latest {rows.length} of {period.trades}
        </span>
        {recent.length > 0 && (
          <Button size="sm" variant="outline" className="h-6 gap-1 px-2 text-[11px]" onClick={() => onMark(recent)}>
            <MapPin className="h-3 w-3" /> Mark {recent.length} on chart
          </Button>
        )}
      </div>
      <div className="max-h-64 overflow-auto">
        <table className="w-full text-[11px]">
          <tbody className="font-mono">
            {rows.map((t, k) => (
              <tr key={`${t.entry_time}-${k}`} className="border-t border-border">
                <td className="py-1 pr-2 whitespace-nowrap">{new Date(t.entry_time).toISOString().slice(0, 16).replace("T", " ")}</td>
                <td className="py-1 pr-2">{t.direction === "long" ? "L" : "S"}</td>
                <td className={cn("py-1 pr-2", t.r > 0 ? "text-emerald-500" : "text-red-400")}>{fmtR(t.r)}</td>
                <td className="py-1 pr-2 font-sans text-muted-foreground">{t.reason}</td>
                <td className="py-1 text-right">
                  {markable(t, meta) ? (
                    <button type="button" onClick={() => onMark([t])} className="text-primary" aria-label="Mark this trade on the chart">
                      <MapPin className="inline h-3 w-3" />
                    </button>
                  ) : (
                    <span className="text-muted-foreground/50" title="Older than the candles the chart loads">—</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function TuningCard({ tuning }: { tuning: TuningReport }) {
  return (
    <section className="space-y-2">
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="text-xs font-semibold text-foreground">Tuned on seen data</h3>
        <span className="font-mono text-[10px] text-muted-foreground">{tuning.tried} settings tried</span>
      </div>
      <p className="text-[11px] text-foreground">Best: {settingLabel(tuning.chosen)}</p>
      <div className="overflow-x-auto">
        <table className="w-full text-[11px]">
          <thead className="text-muted-foreground">
            <tr className="text-left">
              <th className="py-1 pr-2 font-normal">Setting (seen)</th>
              <th className="py-1 pr-2 font-normal">Trades</th>
              <th className="py-1 pr-2 font-normal">Per trade</th>
              <th className="py-1 font-normal">Drawdown</th>
            </tr>
          </thead>
          <tbody className="font-mono">
            {tuning.top.map((row, i) => (
              <tr key={i} className="border-t border-border">
                <td className="py-1 pr-2 font-sans">{settingLabel(row.settings)}</td>
                <td className="py-1 pr-2">{row.trades}</td>
                <td className="py-1 pr-2">{fmtR(row.expectancy_r)}</td>
                <td className="py-1">{fmtPct(row.max_drawdown_pct)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-[10px] leading-relaxed text-muted-foreground">
        Ranked by {tuning.objective}, needing at least {tuning.min_trades} trades.
        {!tuning.qualified && " No setting reached that, so the one with the most trades was taken."} Only the chosen
        setting was run on unseen data — running the runners-up there would make unseen a second tuning set.
      </p>
    </section>
  )
}

export default function BacktestSheet({
  rule,
  open,
  onOpenChange,
  jobId,
}: {
  rule: BacktestRule | null
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Reopen a finished or running backtest instead of setting up a new one. */
  jobId?: string
}) {
  const [neutral, setNeutral] = useState<Neutral>("skip")
  const [sides, setSides] = useState<Sides>("both")
  const [split, setSplit] = useState(0.7)
  const [tune, setTune] = useState(true)
  const [exitPlan, setExitPlan] = useState<ExitPlan>(DEFAULT_EXIT)
  const [tradesPeriod, setTradesPeriod] = useState<"unseen" | "seen">("unseen")
  const [job, setJob] = useState<Backtest | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [starting, setStarting] = useState(false)

  // Closing the sheet forgets the view, not the job: it keeps running on the
  // server. Slice 4 adds a list to reopen it from.
  useEffect(() => {
    if (!open) {
      setJob(null)
      setError(null)
      setStarting(false)
    }
  }, [open])


  // Reopening: load the job this sheet was given.
  useEffect(() => {
    if (!open || !jobId) return
    let cancelled = false
    getBacktest(jobId)
      .then((loaded) => {
        if (!cancelled) setJob(loaded)
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Could not load that backtest")
      })
    return () => {
      cancelled = true
    }
  }, [open, jobId])

  const currentJobId = job?.id
  const running = job !== null && ACTIVE_STATUSES.includes(job.status)
  useEffect(() => {
    if (!currentJobId || !running) return
    const timer = setInterval(async () => {
      try {
        setJob(await getBacktest(currentJobId))
      } catch (err) {
        setError(err instanceof Error ? err.message : "Lost track of the backtest")
      }
    }, POLL_MS)
    return () => clearInterval(timer)
  }, [currentJobId, running])

  if (!rule) return null
  const supported = (BACKTEST_TIMEFRAMES as readonly string[]).includes(rule.timeframe)
  const neutralChoice = canBeNeutral(rule.params)
  const setExit = (patch: Partial<ExitPlan>) => setExitPlan((plan) => ({ ...plan, ...patch }))

  async function start() {
    if (!rule) return
    setStarting(true)
    setError(null)
    try {
      const { id } = await createBacktest(rule, { neutral, sides, split, exit: exitPlan, tune, grid: DEFAULT_GRID })
      setJob(await getBacktest(id))
    } catch (err) {
      setError(
        err instanceof UnauthorizedError
          ? "Sign in with your wallet in the Strategy panel first."
          : err instanceof Error
            ? err.message
            : "Could not start the backtest",
      )
    } finally {
      setStarting(false)
    }
  }

  async function cancel() {
    if (!job) return
    try {
      await cancelBacktest(job.id)
      setJob({ ...job, status: "cancelled" })
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not cancel")
    }
  }

  function mark(trades: TradeRow[]) {
    if (!job?.report) return
    showTradesOnChart({
      symbol: job.report.meta.symbol,
      timeframe: job.report.meta.timeframe,
      marks: trades.flatMap(tradeMarks),
    })
    onOpenChange(false)
  }

  const report = job?.status === "done" ? job.report : null

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-lg">
        <SheetHeader>
          <SheetTitle className="flex items-center gap-2">
            <FlaskConical className="h-4 w-4 text-primary" /> Backtest
          </SheetTitle>
          <SheetDescription>
            {rule.name} · {rule.symbol} {rule.timeframe}
          </SheetDescription>
        </SheetHeader>

        <div className="space-y-4 px-4 pb-6">
          {!supported && <p className="text-xs text-muted-foreground">Backtests run on 5m, 15m, 1h and 1d charts.</p>}

          {supported && job === null && !jobId && (
            <div className="space-y-3">
              <p className="text-xs leading-relaxed text-muted-foreground">
                Replays this rule over stored history exactly as the live alert would have run, measures what price
                did after each signal, and trades it with the exit plan below. The last part of history is held back
                as unseen data.
              </p>
              {neutralChoice && (
                <div className="space-y-1">
                  <span className="text-[11px] text-muted-foreground">This candle has no direction. Read it as</span>
                  <div className="flex gap-1.5">
                    {(["skip", "long", "short"] as Neutral[]).map((n) => (
                      <Button key={n} size="sm" variant={neutral === n ? "default" : "outline"} className="h-7 flex-1 text-xs" onClick={() => setNeutral(n)}>
                        {n === "skip" ? "Skip it" : n === "long" ? "Long" : "Short"}
                      </Button>
                    ))}
                  </div>
                </div>
              )}
              <div className="space-y-1">
                <span className="text-[11px] text-muted-foreground">Directions to trade</span>
                <div className="flex gap-1.5">
                  {SIDES.map((s) => (
                    <Button
                      key={s.value}
                      size="sm"
                      variant={sides === s.value ? "default" : "outline"}
                      className="h-7 flex-1 text-xs"
                      onClick={() => setSides(s.value)}
                    >
                      {s.label}
                    </Button>
                  ))}
                </div>
                {sides === "both" && (
                  <p className="text-[10px] leading-relaxed text-muted-foreground">
                    A spot pool cannot short: a position is the asset or it is stablecoins. Measure long only if this
                    report is meant to justify trading it on-chain.
                  </p>
                )}
              </div>
              <div className="space-y-1">
                <span className="text-[11px] text-muted-foreground">Exit plan</span>
                <div className="grid grid-cols-3 gap-2">
                  <NumberField label="Stop (× ATR)" value={exitPlan.stop_atr} step={0.25} onChange={(v) => setExit({ stop_atr: v > 0 ? v : DEFAULT_EXIT.stop_atr })} />
                  <NumberField label="Target (× risk)" value={exitPlan.target_r} step={0.5} onChange={(v) => setExit({ target_r: v > 0 ? v : null })} />
                  <NumberField label="Max bars held" value={exitPlan.max_bars} step={1} onChange={(v) => setExit({ max_bars: Math.max(1, Math.round(v) || 1) })} />
                </div>
              </div>
              <div className="space-y-1">
                <span className="text-[11px] text-muted-foreground">Pool fee — paid on every swap, so twice per trade</span>
                <div className="flex gap-1.5">
                  {POOL_TIERS.map((tier) => (
                    <Button
                      key={tier.pct}
                      size="sm"
                      variant={exitPlan.fee_pct === tier.pct ? "default" : "outline"}
                      className="h-7 flex-1 px-1 text-[11px]"
                      onClick={() => setExit({ fee_pct: tier.pct })}
                      title={`${tier.pct}% pool — ${tier.what}`}
                    >
                      {tier.pct}%
                    </Button>
                  ))}
                </div>
                <div className="grid grid-cols-3 gap-2">
                  <NumberField label="Price impact %" value={exitPlan.slippage_pct} step={0.01} onChange={(v) => setExit({ slippage_pct: Math.max(0, v) })} />
                  <NumberField label="Gas per swap $" value={exitPlan.gas_usd} step={0.1} onChange={(v) => setExit({ gas_usd: Math.max(0, v) })} />
                  <NumberField label="Position size $" value={exitPlan.trade_usd} step={100} onChange={(v) => setExit({ trade_usd: v > 0 ? v : DEFAULT_EXIT.trade_usd })} />
                </div>
                <div className="grid grid-cols-3 gap-2">
                  <NumberField label="Risk per trade %" value={exitPlan.risk_pct} step={0.25} onChange={(v) => setExit({ risk_pct: v > 0 ? v : DEFAULT_EXIT.risk_pct })} />
                </div>
                <p className="text-[10px] leading-relaxed text-muted-foreground">
                  A round trip costs {roundTripPct(exitPlan).toFixed(3)}% of the position
                  {exitPlan.gas_usd > 0 && ` — gas is ${gasPct(exitPlan).toFixed(3)}% of that at this size`}. Costs in R
                  are that over your stop distance, so for them to stay under {COST_BUDGET_R}R the stop needs to be at
                  least {stopPctForCostBudget(exitPlan, COST_BUDGET_R).toFixed(2)}% of price away. A tighter stop, or a
                  faster timeframe, and the pool decides the result rather than the signal.
                </p>
              </div>
              <div className="space-y-1">
                <span className="text-[11px] text-muted-foreground">Tuning</span>
                <div className="flex gap-1.5">
                  <Button size="sm" variant={tune ? "default" : "outline"} className="h-7 flex-1 text-xs" onClick={() => setTune(true)}>
                    Tune on seen data
                  </Button>
                  <Button size="sm" variant={!tune ? "default" : "outline"} className="h-7 flex-1 text-xs" onClick={() => setTune(false)}>
                    Use my plan as is
                  </Button>
                </div>
                <p className="text-[10px] leading-relaxed text-muted-foreground">
                  {tune
                    ? "Tries a grid of stops, targets and holding times on the seen part of history, then runs only the best one on the unseen part. The report says how many were tried."
                    : "Runs the exit plan above on both periods, with nothing selected after the fact."}
                </p>
              </div>
              <div className="space-y-1">
                <span className="text-[11px] text-muted-foreground">Seen / unseen split</span>
                <div className="flex gap-1.5">
                  {SPLITS.map((s) => (
                    <Button key={s} size="sm" variant={split === s ? "default" : "outline"} className="h-7 flex-1 font-mono text-xs" onClick={() => setSplit(s)}>
                      {Math.round(s * 100)} / {Math.round((1 - s) * 100)}
                    </Button>
                  ))}
                </div>
              </div>
              <Button onClick={start} disabled={starting} className="h-9 w-full text-xs">
                {starting ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> : <FlaskConical className="mr-1 h-3.5 w-3.5" />}
                Run backtest
              </Button>
            </div>
          )}

          {job && ACTIVE_STATUSES.includes(job.status) && (
            <div className="space-y-2">
              <p className="text-xs text-foreground">{STAGE[job.status]}…</p>
              <Progress value={Math.round(job.progress * 100)} />
              <div className="flex items-center justify-between">
                <span className="font-mono text-[10px] text-muted-foreground">{Math.round(job.progress * 100)}%</span>
                <Button size="sm" variant="outline" className="h-7 text-xs" onClick={cancel}>
                  Cancel
                </Button>
              </div>
              <p className="text-[10px] text-muted-foreground">
                The first run of a rule replays every bar and can take many minutes. It keeps running if you close this.
              </p>
            </div>
          )}

          {job?.status === "failed" && <p className="text-xs text-destructive">{job.error}</p>}
          {job?.status === "cancelled" && <p className="text-xs text-muted-foreground">Cancelled.</p>}

          {report && (
            <div className="space-y-5">
              <div className="space-y-2 rounded-md border border-border bg-secondary px-3 py-2 text-xs text-foreground">
                <p>{verdict(report)}</p>
                {tradeVerdict(report) && <p>{tradeVerdict(report)}</p>}
              </div>

              {overfit(report) && (
                <p className="rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-[11px] text-amber-500">
                  Unseen came in far below seen. That is what a setting fitted to the seen data looks like; treat the
                  unseen numbers as the honest ones.
                </p>
              )}
              {report.tuning && <TuningCard tuning={report.tuning} />}
              {report.trades && (
                <section className="space-y-3">
                  <h3 className="text-xs font-semibold text-foreground">Trading it</h3>
                  <EquityChart seen={report.trades.seen} unseen={report.trades.unseen} />
                  <MetricsTable seen={report.trades.seen} unseen={report.trades.unseen} />
                  <div className="flex gap-1.5">
                    {(["unseen", "seen"] as const).map((p) => (
                      <Button key={p} size="sm" variant={tradesPeriod === p ? "default" : "outline"} className="h-6 flex-1 text-[11px] capitalize" onClick={() => setTradesPeriod(p)}>
                        {p} trades
                      </Button>
                    ))}
                  </div>
                  <TradeList period={report.trades[tradesPeriod]} meta={report.meta} onMark={mark} />
                  {[...report.trades.seen.trade_list, ...report.trades.unseen.trade_list].some((t) => t.direction === "short") && (
                    <p className="text-[10px] text-muted-foreground">
                      Short trades assume you can sell what you do not hold — futures or margin, not spot.
                    </p>
                  )}
                </section>
              )}

              <section className="space-y-3">
                <h3 className="text-xs font-semibold text-foreground">Does the signal predict anything?</h3>
                <StudyTable title="Unseen" period={report.study.unseen} />
                <StudyTable title="Seen" period={report.study.seen} />
              </section>

              <p className="text-[10px] leading-relaxed text-muted-foreground">
                {report.signals.fires} alerts from {report.signals.setups} distinct setups over{" "}
                {report.meta.bars.toLocaleString()} bars; each setup counts and trades once. Fills assume the worse
                case inside a bar and pay the pool fee, the gas and the price impact of the plan above.{" "}
                {report.meta.tape_cached ? "Replay reused from cache." : `Replay took ${Math.round(report.meta.replay_seconds)}s.`}{" "}
                Past behaviour on this data is not a forecast.
              </p>
            </div>
          )}

          {error && <p className="text-xs text-destructive">{error}</p>}
        </div>
      </SheetContent>
    </Sheet>
  )
}
