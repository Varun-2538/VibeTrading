"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import { Loader2, ShieldCheck } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import {
  getBacktest,
  listBacktests,
  settingLabel,
  type BacktestReport,
  type BacktestSummary,
} from "@/lib/backtests"
import {
  armRule,
  disarmRule,
  fmtR,
  getAccount,
  listPolicies,
  marketForSymbol,
  preflight,
  refusalLines,
  type ArmedPolicy,
  type ExecutionAccount,
  type PreflightResult,
} from "@/lib/execution"
import { UnauthorizedError, type Rule } from "@/lib/rules"

const DEFAULT_EXPECTANCY = 0.1
const DEFAULT_DRAWDOWN = 25
const DEFAULT_CAP = 100

/**
 * Letting a rule trade itself.
 *
 * The shape of this screen is an argument: you cannot type an exit plan here. The
 * plan comes from the backtest you pick, read out of its report, because the whole
 * point of the gate is that what trades is what was measured. A field that let you
 * arm a different stop than the one the report tested would quietly undo it.
 *
 * What you do set is the bar the report has to clear and how much money a trade may
 * use. Both are yours; neither can be set to nothing.
 */
export default function ArmSheet({
  rule,
  open,
  onOpenChange,
  onChanged,
}: {
  rule: Rule | null
  open: boolean
  onOpenChange: (open: boolean) => void
  onChanged?: () => void
}) {
  const [account, setAccount] = useState<ExecutionAccount | null>(null)
  const [policy, setPolicy] = useState<ArmedPolicy | null>(null)
  const [runs, setRuns] = useState<BacktestSummary[]>([])
  const [chosen, setChosen] = useState<string | null>(null)
  const [report, setReport] = useState<BacktestReport | null>(null)
  const [expectancy, setExpectancy] = useState(DEFAULT_EXPECTANCY)
  const [drawdown, setDrawdown] = useState(DEFAULT_DRAWDOWN)
  const [cap, setCap] = useState(DEFAULT_CAP)
  const [result, setResult] = useState<PreflightResult | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const market = rule ? marketForSymbol(rule.symbol) : null

  const load = useCallback(async () => {
    if (!rule) return
    setError(null)
    try {
      const [acc, policies, jobs] = await Promise.all([getAccount(), listPolicies(), listBacktests()])
      setAccount(acc)
      setPolicy(policies.find((p) => p.rule_id === rule.id) ?? null)
      // Only this rule's finished runs: a report about something else is not evidence,
      // and the gate would refuse it anyway with a less helpful message than this.
      setRuns(jobs.filter((j) => j.rule_id === rule.id && j.status === "done"))
    } catch (err) {
      if (err instanceof UnauthorizedError) {
        setError("Sign in with your wallet first.")
        return
      }
      setError(err instanceof Error ? err.message : "Could not read your execution account")
    }
  }, [rule])

  useEffect(() => {
    if (!open) return
    setResult(null)
    setChosen(null)
    setReport(null)
    void load()
  }, [open, load])

  useEffect(() => {
    if (!chosen) {
      setReport(null)
      return
    }
    let alive = true
    void (async () => {
      try {
        const job = await getBacktest(chosen)
        if (alive) setReport(job.report ?? null)
      } catch {
        if (alive) setReport(null)
      }
    })()
    return () => {
      alive = false
    }
  }, [chosen])

  const exitPlan = useMemo(() => (report?.meta.exit ?? null), [report])
  const unseen = report?.trades?.unseen ?? null

  async function check() {
    if (!rule || !market || !chosen || !exitPlan) return
    setBusy("check")
    setError(null)
    try {
      setResult(
        await preflight(rule.id, {
          market,
          backtest_job_id: chosen,
          exit: exitPlan as unknown as Record<string, unknown>,
          neutral: (report?.meta.neutral as "skip" | "long" | "short") ?? "skip",
          max_notional_usd: cap,
          thresholds: { min_expectancy_r: expectancy, max_drawdown_pct: drawdown },
        }),
      )
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not run the check")
    } finally {
      setBusy(null)
    }
  }

  async function arm() {
    if (!rule || !market || !chosen || !exitPlan) return
    setBusy("arm")
    setError(null)
    try {
      setPolicy(
        await armRule(rule.id, {
          market,
          backtest_job_id: chosen,
          exit: exitPlan as unknown as Record<string, unknown>,
          neutral: (report?.meta.neutral as "skip" | "long" | "short") ?? "skip",
          max_notional_usd: cap,
          thresholds: { min_expectancy_r: expectancy, max_drawdown_pct: drawdown },
        }),
      )
      onChanged?.()
    } catch (err) {
      // A refusal arrives as a 409 whose detail carries every reason. Showing one line
      // of it would waste the only place that explains why a strategy may not spend.
      setError(err instanceof Error ? err.message : "Could not arm this rule")
    } finally {
      setBusy(null)
    }
  }

  async function disarm() {
    if (!rule) return
    setBusy("disarm")
    try {
      setPolicy(await disarmRule(rule.id))
      onChanged?.()
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not stop this rule trading")
    } finally {
      setBusy(null)
    }
  }

  const refusals = refusalLines(result)

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-md">
        <SheetHeader>
          <SheetTitle className="flex items-center gap-2 text-sm">
            <ShieldCheck className="h-4 w-4" /> Let this rule trade
          </SheetTitle>
          <SheetDescription className="text-xs leading-relaxed">
            {rule
              ? `${rule.name} — ${rule.symbol} ${rule.timeframe}. It keeps alerting either way; this decides whether it also trades, inside your own vault.`
              : ""}
          </SheetDescription>
        </SheetHeader>

        <div className="space-y-5 px-4 pb-8 pt-2">
          {market === null ? (
            <p className="rounded border border-border bg-secondary/40 p-2 text-[11px] leading-relaxed text-muted-foreground">
              {rule?.symbol} cannot be traded on-chain here. A vault needs a deep Uniswap pool and a
              Chainlink price feed, and only ETH and BTC have both — so a rule on this pair can alert as
              much as you like and can never be armed to trade.
            </p>
          ) : policy?.armed ? (
            <section className="space-y-2">
              <p className="text-[11px] leading-relaxed text-foreground">
                Trading {policy.market}, armed{" "}
                {policy.armed_at ? new Date(policy.armed_at).toISOString().slice(0, 16).replace("T", " ") : ""}.
              </p>
              {policy.preflight?.evidence ? (
                <table className="w-full text-[11px]">
                  <tbody className="font-mono">
                    <tr className="border-t border-border">
                      <td className="py-1 pr-2 font-sans text-muted-foreground">Evidence</td>
                      <td className="py-1 text-right">
                        {String(policy.preflight.evidence.unseen_trades ?? "—")} unseen trades,{" "}
                        {fmtR(Number(policy.preflight.evidence.unseen_expectancy_r ?? 0))}
                      </td>
                    </tr>
                  </tbody>
                </table>
              ) : null}
              {!policy.parity_current && (
                <p className="text-[11px] leading-relaxed text-destructive">
                  This was armed under different exit arithmetic and will not trade until it is armed
                  again from a fresh backtest.
                </p>
              )}
              <Button
                size="sm"
                variant="outline"
                className="h-7 w-full text-xs"
                disabled={busy !== null}
                onClick={disarm}
              >
                {busy === "disarm" ? <Loader2 className="h-3 w-3 animate-spin" /> : "Stop trading this rule"}
              </Button>
              <p className="text-[10px] leading-relaxed text-muted-foreground">
                Stopping prevents anything new from opening. A position that is already open still closes
                on its own stop, target or deadline, because those live in the contract.
              </p>
            </section>
          ) : (
            <>
              <section className="space-y-1.5">
                <span className="text-[11px] text-muted-foreground">The backtest this trades on</span>
                {runs.length === 0 ? (
                  <p className="text-[11px] leading-relaxed text-muted-foreground">
                    No finished backtest for this rule yet. Run one from the Armed tab — long-only, since a
                    pool cannot short — and come back.
                  </p>
                ) : (
                  <div className="space-y-1">
                    {runs.slice(0, 6).map((run) => (
                      <button
                        key={run.id}
                        type="button"
                        onClick={() => setChosen(run.id)}
                        className={`flex w-full items-center justify-between rounded border px-2 py-1 text-left text-[11px] ${
                          chosen === run.id ? "border-primary bg-secondary" : "border-border hover:bg-secondary/60"
                        }`}
                      >
                        <span className="font-mono">
                          {run.created_at ? new Date(run.created_at).toISOString().slice(0, 10) : run.id.slice(0, 8)}
                        </span>
                        <span className="text-muted-foreground">
                          {run.request?.rule?.timeframe ?? ""}
                        </span>
                      </button>
                    ))}
                  </div>
                )}
              </section>

              {exitPlan && (
                <section className="space-y-1">
                  <span className="text-[11px] text-muted-foreground">What it will trade, as measured</span>
                  <p className="font-mono text-[11px] text-foreground">
                    {settingLabel({
                      filters: {},
                      stop_atr: Number(exitPlan.stop_atr ?? 0),
                      target_r: Number(exitPlan.target_r ?? 0),
                      max_bars: Number(exitPlan.max_bars ?? 0),
                    })}
                  </p>
                  {unseen && (
                    <p className="text-[10px] leading-relaxed text-muted-foreground">
                      On unseen data: {unseen.trades} trades, {fmtR(unseen.expectancy_r)} each after costs
                      {unseen.cost_r ? `, of which ${fmtR(-unseen.cost_r)} went to costs` : ""}.
                    </p>
                  )}
                  <p className="text-[10px] leading-relaxed text-muted-foreground">
                    You cannot edit this here. What trades is what was measured — a different stop would
                    be a different strategy, and the report would no longer be about it.
                  </p>
                </section>
              )}

              <section className="space-y-1">
                <span className="text-[11px] text-muted-foreground">Your bar, and your size</span>
                <div className="grid grid-cols-3 gap-2">
                  <Field label="Min per trade (R)" value={expectancy} step={0.05} onChange={setExpectancy} />
                  <Field label="Max drawdown %" value={drawdown} step={5} onChange={setDrawdown} />
                  <Field label="Max per trade $" value={cap} step={25} onChange={setCap} />
                </div>
                <p className="text-[10px] leading-relaxed text-muted-foreground">
                  The bar is yours to set, but not to zero: there is no reading of a losing unseen result
                  that makes it evidence. Thirty trades is the minimum sample either way.
                </p>
              </section>

              <div className="flex gap-1.5">
                <Button
                  size="sm"
                  variant="outline"
                  className="h-7 flex-1 text-xs"
                  disabled={!chosen || !exitPlan || busy !== null}
                  onClick={check}
                >
                  {busy === "check" ? <Loader2 className="h-3 w-3 animate-spin" /> : "Check it"}
                </Button>
                <Button
                  size="sm"
                  className="h-7 flex-1 text-xs"
                  disabled={!result?.passed || busy !== null}
                  onClick={arm}
                >
                  {busy === "arm" ? <Loader2 className="h-3 w-3 animate-spin" /> : "Let it trade"}
                </Button>
              </div>

              {result?.passed && (
                <p className="text-[11px] leading-relaxed text-foreground">
                  This clears your bar. Arming it does not start anything by itself: your account also has
                  to be out of off, and it is worth a week in shadow first.
                </p>
              )}
              {refusals.length > 0 && (
                <ul className="space-y-1 rounded border border-destructive/40 bg-destructive/10 p-2">
                  {refusals.map((reason) => (
                    <li key={reason} className="text-[11px] leading-relaxed text-destructive">
                      {reason}
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}

          {account && !account.execution_enabled && (
            <p className="text-[10px] leading-relaxed text-muted-foreground">
              Execution is switched off on the server, so nothing armed here will trade yet. That is the
              current state of the feature, not a problem with your rule.
            </p>
          )}
          {error && <p className="text-[11px] text-destructive">{error}</p>}
        </div>
      </SheetContent>
    </Sheet>
  )
}

function Field({
  label,
  value,
  step,
  onChange,
}: {
  label: string
  value: number
  step: number
  onChange: (value: number) => void
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</span>
      <Input
        type="number"
        inputMode="decimal"
        step={step}
        min={0}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="h-7 px-2 font-mono text-xs"
      />
    </label>
  )
}
