import { describe, expect, it } from "vitest"

import { canBeNeutral, fmtPct, verdict, type BacktestReport, type PeriodStudy } from "@/lib/backtests"

function period(over: Partial<PeriodStudy> = {}, edge = 0.4, ci: [number, number] | null = [0.1, 0.7]): PeriodStudy {
  return {
    from: 0, to: 1, bars: 1000, signals: 45, skipped_neutral: 0, long_share: 0.5,
    horizons: [1, 5, 10, 20].map((h) => ({
      h, signals: 45, mean_pct: edge, baseline_pct: 0, edge_pct: edge, ci_pct: ci, hit_rate: 0.55, baseline_hit_rate: 0.5,
    })),
    mfe_atr: 1.2, mae_atr: 0.8, flags: [],
    ...over,
  }
}

function report(unseen: PeriodStudy): BacktestReport {
  return {
    meta: { symbol: "BTCUSDT", timeframe: "1h", name: "x", neutral: "skip", split: 0.7, bars: 1, warmup_bars: 0,
            from: 0, to: 1, split_time: 0, tape_cached: false, replay_seconds: 1 },
    signals: { fires: 50, setups: 45 },
    study: { seen: period(), unseen },
  }
}

describe("canBeNeutral", () => {
  it("is true only for sequences ending on a directionless candle", () => {
    expect(canBeNeutral({ agent: "sequence", steps: [{ type: "candle", shape: "doji" }], within_bars: 3 })).toBe(true)
    expect(canBeNeutral({ agent: "sequence", steps: [{ type: "candle", shape: "hammer" }], within_bars: 3 })).toBe(false)
    expect(canBeNeutral({ agent: "pattern", kinds: ["W"] })).toBe(false)
  })
})

describe("verdict", () => {
  it("says too few before anything else", () => {
    expect(verdict(report(period({ signals: 12, flags: ["too_few_signals", "no_edge_detected"] })))).toMatch(/Only 12 unseen signals/)
  })
  it("says no edge plainly", () => {
    expect(verdict(report(period({ flags: ["no_edge_detected"] }, 0.05, [-0.3, 0.4])))).toMatch(/^No edge on unseen data/)
  })
  it("reports an edge with its interval", () => {
    expect(verdict(report(period()))).toBe(
      "Unseen edge +0.40% per signal over 10 bars (95% CI +0.10% to +0.70%), across 45 signals.",
    )
  })
  it("handles no unseen signals", () => {
    expect(verdict(report(period({ signals: 0, flags: ["too_few_signals", "no_edge_detected"] }, 0, null)))).toBe(
      "No signals on unseen data — nothing to judge.",
    )
  })
})

describe("fmtPct", () => {
  it("signs and dashes", () => {
    expect(fmtPct(0.4)).toBe("+0.40%")
    expect(fmtPct(-1.234)).toBe("-1.23%")
    expect(fmtPct(null)).toBe("—")
  })
})
