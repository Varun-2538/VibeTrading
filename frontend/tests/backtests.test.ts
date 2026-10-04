import { describe, expect, it } from "vitest"

import { canBeNeutral, costNote, DEFAULT_EXIT, equityLines, fmtPct, gasPct, markable, overfit, POOL_TIERS, roundTripPct, settingLabel, SIDES, stopPctForCostBudget, tradeMarks, tradeVerdict, verdict, type BacktestReport, type PeriodStudy, type TradePeriod, type TradeRow, type TuningReport } from "@/lib/backtests"

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
    gross_expectancy_r: 0.5, cost_r: 0.15,
    profit_factor: 1.6, total_return_pct: 12.5, max_drawdown_pct: -6.2, sharpe: 1.1, exposure_pct: 30,
    longest_losing_streak: 5, buy_hold_pct: 20, skipped_in_position: 0, skipped_neutral: 0, skipped_no_room: 0,
    equity: [], trade_list: [], trades_listed: 0, flags: [],
    ...over,
  }
}

describe("trades", () => {
  const trade: TradeRow = { entry_time: 10_000, entry: 100, exit_time: 20_000, exit: 104, direction: "long", reason: "target", r: 2, cost_r: 0.2, pct: 4, bars: 3 }

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
      "Trading it on unseen data: +0.35R per trade over 40 unseen trades, +12.50% total, worst drawdown -6.20% (seen: +0.50R per trade). Costs took -0.15R per trade: +0.50R before them, +0.35R after.",
    )
    expect(tradeVerdict({ ...base, trades: { seen: tp(), unseen: tp({ trades: 7, flags: ["too_few_trades"] }) } })).toBe(
      "Only 7 unseen trades — too few to judge this exit plan.",
    )
    expect(tradeVerdict(base)).toBeNull()
  })

  it("separates a strategy with no edge from one whose edge went to the pool", () => {
    // A 0.3% pool, twice, against a tight stop: the signals won, the account did not.
    expect(costNote(tp({ expectancy_r: -0.1, gross_expectancy_r: 0.25, cost_r: 0.35 }))).toBe(
      " Costs took -0.35R per trade: +0.25R before them, -0.10R after. The signals earned an edge and the pool kept it.",
    )
    // Nothing to explain away: it lost before costs too.
    expect(costNote(tp({ expectancy_r: -0.4, gross_expectancy_r: -0.1, cost_r: 0.3 }))).toBe(
      " Costs took -0.30R per trade: -0.10R before them, -0.40R after.",
    )
    expect(costNote(tp({ expectancy_r: 0.2, gross_expectancy_r: 0.2, cost_r: 0 }))).toBe("")
  })

  it("offers the directions a venue can take, and defaults to measuring both", () => {
    // The default keeps every existing report comparable; the spot venue needs
    // "long" and the arming gate is what will insist on it.
    expect(SIDES.map((s) => s.value)).toEqual(["both", "long", "short"])
    expect(SIDES[1].label).toBe("Long only")
  })

  it("prices a round trip the way the pool does", () => {
    const free = { ...DEFAULT_EXIT, fee_pct: 0, slippage_pct: 0 }
    expect(roundTripPct(free)).toBe(0)
    // The 0.3% pool with $2 of gas on a $500 position: 0.3 + 0.4 per swap, twice.
    expect(roundTripPct({ ...free, fee_pct: 0.3, gas_usd: 2, trade_usd: 500 })).toBeCloseTo(1.4, 6)
    expect(gasPct({ ...free, gas_usd: 0.5, trade_usd: 1000 })).toBeCloseTo(0.05, 6)
    expect(POOL_TIERS.map((t) => t.pct)).toEqual([0.01, 0.05, 0.1, 0.3, 1])
    expect(POOL_TIERS.some((t) => t.pct === DEFAULT_EXIT.fee_pct)).toBe(true)
  })

  it("says how wide a stop the round trip needs", () => {
    // 0.3% pool, no gas, no impact: 0.6% a round trip, so 0.2R of cost wants a 3% stop.
    const pool = { ...DEFAULT_EXIT, fee_pct: 0.3, slippage_pct: 0, gas_usd: 0 }
    expect(stopPctForCostBudget(pool, 0.2)).toBeCloseTo(3, 6)
    expect(stopPctForCostBudget(pool, 0.6)).toBeCloseTo(1, 6)
    expect(stopPctForCostBudget({ ...pool, fee_pct: 0.01 }, 0.2)).toBeCloseTo(0.1, 6)
  })
})


function tuning(over: Partial<TuningReport> = {}): TuningReport {
  const settings = { filters: {}, stop_atr: 1.5, target_r: 2, max_bars: 20 }
  return {
    tried: 27, objective: "expectancy in R per trade on seen data", min_trades: 30, qualified: true,
    chosen: settings,
    top: [{ settings, trades: 44, expectancy_r: 0.4, max_drawdown_pct: -8, total_return_pct: 15 }],
    ...over,
  }
}

describe("tuning", () => {
  it("labels a setting the way a trader would read it", () => {
    expect(settingLabel({ filters: {}, stop_atr: 1.5, target_r: 2, max_bars: 20 })).toBe("stop 1.5 ATR · target 2R · 20 bars")
    expect(settingLabel({ filters: { min_confidence: 70 }, stop_atr: 1, target_r: 3, max_bars: 10 })).toBe(
      "stop 1 ATR · target 3R · 10 bars · confidence 70",
    )
    expect(settingLabel({ filters: { min_strength: "strong" }, stop_atr: 2, target_r: 1, max_bars: 40 })).toBe(
      "stop 2 ATR · target 1R · 40 bars · strength strong",
    )
  })

  it("says a tuned verdict was selected from many tries, and flags a collapse", () => {
    const base = report(period())
    const tuned = { ...base, tuning: tuning(), flags: ["tuned", "likely_overfit"], trades: { seen: tp({ expectancy_r: 0.9 }), unseen: tp() } }
    expect(tradeVerdict(tuned)).toBe(
      "Selected from 27 settings: +0.35R per trade over 40 unseen trades, +12.50% total, worst drawdown -6.20% (seen: +0.90R per trade) — far below seen, so likely fitted to the seen data. Costs took -0.15R per trade: +0.50R before them, +0.35R after.",
    )
    expect(overfit(tuned)).toBe(true)
    expect(overfit({ ...base, trades: { seen: tp(), unseen: tp() } })).toBe(false)
  })
})
