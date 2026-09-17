import { describe, expect, it } from "vitest"

import { canBeNeutral, equityLines, fmtPct, markable, tradeMarks, tradeVerdict, verdict, type BacktestReport, type PeriodStudy, type TradePeriod, type TradeRow } from "@/lib/backtests"

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


function tp(over: Partial<TradePeriod> = {}): TradePeriod {
  return {
    from: 0, to: 1, bars: 100, trades: 40, win_rate: 0.45, avg_win_r: 2, avg_loss_r: -1, expectancy_r: 0.35,
    profit_factor: 1.6, total_return_pct: 12.5, max_drawdown_pct: -6.2, sharpe: 1.1, exposure_pct: 30,
    longest_losing_streak: 5, buy_hold_pct: 20, skipped_in_position: 0, skipped_neutral: 0, skipped_no_room: 0,
    equity: [], trade_list: [], trades_listed: 0, flags: [],
    ...over,
  }
}

describe("trades", () => {
  const trade: TradeRow = { entry_time: 10_000, entry: 100, exit_time: 20_000, exit: 104, direction: "long", reason: "target", r: 2, pct: 4, bars: 3 }

  it("marks an entry and an exit", () => {
    expect(tradeMarks(trade)).toEqual([
      { type: "bar", time: 10_000, position: "below", shape: "arrowUp", text: "Long" },
      { type: "bar", time: 20_000, position: "above", shape: "circle", text: "+2.00R target" },
    ])
  })

  it("only offers trades inside the chart's loaded window", () => {
    const hour = 3_600_000
    const to = 5000 * hour
    expect(markable({ ...trade, entry_time: to - 100 * hour }, { to, timeframe: "1h" })).toBe(true)
    expect(markable({ ...trade, entry_time: to - 2000 * hour }, { to, timeframe: "1h" })).toBe(false)
  })

  it("draws unseen equity continuing from seen, on a time axis", () => {
    const lines = equityLines([[0, 1], [10, 1.1]], [[10, 1], [20, 0.5]], 100, 50)
    expect(lines.boundaryX).toBe(50)
    expect(lines.seen).toBe("0.0,9.1 50.0,0.0")
    expect(lines.unseen).toBe("50.0,0.0 50.0,0.0 100.0,50.0")
  })

  it("sums up the unseen trades, or says there are too few", () => {
    const base = report(period())
    expect(tradeVerdict({ ...base, trades: { seen: tp({ expectancy_r: 0.5 }), unseen: tp() } })).toBe(
      "Trading it on unseen data: +0.35R per trade over 40 trades, +12.50% total, worst drawdown -6.20% (seen: +0.50R per trade).",
    )
    expect(tradeVerdict({ ...base, trades: { seen: tp(), unseen: tp({ trades: 7, flags: ["too_few_trades"] }) } })).toBe(
      "Only 7 unseen trades — too few to judge this exit plan.",
    )
    expect(tradeVerdict(base)).toBeNull()
  })
})
