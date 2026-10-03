"use client"

import { useEffect, useState } from "react"
import { FlaskConical, Loader2 } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Progress } from "@/components/ui/progress"
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import {
  ACTIVE_STATUSES,
  BACKTEST_TIMEFRAMES,
  canBeNeutral,
  cancelBacktest,
  createBacktest,
  fmtPct,
  getBacktest,
  verdict,
  type Backtest,
  type BacktestRule,
  type Neutral,
  type PeriodStudy,
} from "@/lib/backtests"
import { UnauthorizedError } from "@/lib/rules"
import { cn } from "@/lib/utils"

const POLL_MS = 3000
const SPLITS = [0.6, 0.7, 0.8]
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
        {period.flags.includes("too_few_signals") && " · too few signals to judge"}
      </p>
    </div>
  )
}

export default function BacktestSheet({
  rule,
  open,
  onOpenChange,
}: {
  rule: BacktestRule | null
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const [neutral, setNeutral] = useState<Neutral>("skip")
  const [split, setSplit] = useState(0.7)
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

  const jobId = job?.id
  const running = job !== null && ACTIVE_STATUSES.includes(job.status)
  useEffect(() => {
    if (!jobId || !running) return
    const timer = setInterval(async () => {
      try {
        setJob(await getBacktest(jobId))
      } catch (err) {
        setError(err instanceof Error ? err.message : "Lost track of the backtest")
      }
    }, POLL_MS)
    return () => clearInterval(timer)
  }, [jobId, running])

  if (!rule) return null
  const supported = (BACKTEST_TIMEFRAMES as readonly string[]).includes(rule.timeframe)
  const neutralChoice = canBeNeutral(rule.params)

  async function start() {
    if (!rule) return
    setStarting(true)
    setError(null)
    try {
      const { id } = await createBacktest(rule, { neutral, split })
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
          {!supported && (
            <p className="text-xs text-muted-foreground">Backtests run on 5m, 15m, 1h and 1d charts.</p>
          )}

          {supported && job === null && (
            <div className="space-y-3">
              <p className="text-xs leading-relaxed text-muted-foreground">
                Replays this rule over stored history exactly as the live alert would have run, then measures
                what price did after each signal against the market as a whole. The last part of history is
                held back as unseen data.
              </p>
              {neutralChoice && (
                <div className="space-y-1">
                  <span className="text-[11px] text-muted-foreground">This candle has no direction. Read it as</span>
                  <div className="flex gap-1.5">
                    {(["skip", "long", "short"] as Neutral[]).map((n) => (
                      <Button key={n} size="sm" variant={neutral === n ? "default" : "outline"}
                        className="h-7 flex-1 text-xs" onClick={() => setNeutral(n)}>
                        {n === "skip" ? "Skip it" : n === "long" ? "Long" : "Short"}
                      </Button>
                    ))}
                  </div>
                </div>
              )}
              <div className="space-y-1">
                <span className="text-[11px] text-muted-foreground">Seen / unseen split</span>
                <div className="flex gap-1.5">
                  {SPLITS.map((s) => (
                    <Button key={s} size="sm" variant={split === s ? "default" : "outline"}
                      className="h-7 flex-1 font-mono text-xs" onClick={() => setSplit(s)}>
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
                <Button size="sm" variant="outline" className="h-7 text-xs" onClick={cancel}>Cancel</Button>
              </div>
              <p className="text-[10px] text-muted-foreground">
                The first run of a rule replays every bar and can take many minutes. It keeps running if you close this.
              </p>
            </div>
          )}

          {job?.status === "failed" && <p className="text-xs text-destructive">{job.error}</p>}
          {job?.status === "cancelled" && <p className="text-xs text-muted-foreground">Cancelled.</p>}

          {job?.status === "done" && job.report && (
            <div className="space-y-4">
              <p className="rounded-md border border-border bg-secondary px-3 py-2 text-xs text-foreground">
                {verdict(job.report)}
              </p>
              <StudyTable title="Unseen" period={job.report.study.unseen} />
              <StudyTable title="Seen" period={job.report.study.seen} />
              <p className="text-[10px] leading-relaxed text-muted-foreground">
                {job.report.signals.fires} alerts from {job.report.signals.setups} distinct setups over{" "}
                {job.report.meta.bars.toLocaleString()} bars. Each setup counts once.{" "}
                {job.report.meta.tape_cached ? "Replay reused from cache." : `Replay took ${Math.round(job.report.meta.replay_seconds)}s.`}{" "}
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
