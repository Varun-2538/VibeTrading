import { describe, expect, it } from "vitest"

import { TRIGGERS, signalParams, stepWarmup, triggerById, triggerName } from "@/lib/triggers"

describe("the trigger catalogue", () => {
  it("covers every step type the server knows", () => {
    expect(TRIGGERS.map((t) => t.id).sort()).toEqual([
      "atr_expansion", "bollinger", "bollinger_squeeze", "candle", "ema_cross",
      "macd_cross", "rsi", "stoch_cross", "structure", "vwap_cross", "volume_spike",
    ].sort())
  })

  it("builds each trigger from its own defaults", () => {
    for (const def of TRIGGERS) {
      const step = def.build(def.defaults)
      expect(step.type).toBeTruthy()
      expect(stepWarmup(step)).toBeGreaterThan(0)
    }
  })

  it("builds an EMA cross with the values given", () => {
    const def = triggerById("ema_cross")!
    expect(def.build({ ...def.defaults, fast: 50, slow: 200, cross: "below" })).toEqual({
      type: "ema_cross", fast: 50, slow: 200, cross: "below",
    })
  })

  it("mirrors the server's warm-up arithmetic", () => {
    expect(stepWarmup({ type: "ema_cross", fast: 20, slow: 50, cross: "above" })).toBe(50)
    expect(stepWarmup({ type: "macd_cross", fast: 12, slow: 26, signal: 9, against: "signal", cross: "above" })).toBe(35)
    expect(stepWarmup({ type: "bollinger_squeeze", period: 20, lookback: 120 })).toBe(140)
    expect(stepWarmup({ type: "candle", shape: "doji" })).toBe(2)
  })

  it("asks for a lookback long enough for the step", () => {
    const squeeze = triggerById("bollinger_squeeze")!
    const params = signalParams(squeeze, squeeze.defaults)
    expect(params.agent).toBe("sequence")
    expect(params.lookback!).toBeGreaterThanOrEqual(140 + 3 + 2)
    expect(params.steps).toHaveLength(1)
    expect(params.within_bars).toBe(3)
  })

  it("names a rule after what it watches", () => {
    const def = triggerById("vwap_cross")!
    expect(triggerName(def, { ...def.defaults, anchor: "week", cross: "above" })).toBe("VWAP cross")
  })
})
