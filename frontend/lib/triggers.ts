import type { SequenceRuleParams, SequenceStep } from "@/lib/rules"

/**
 * What the Strategy panel can build as a one-step rule.
 *
 * One entry per step type the server accepts, with its fields, its defaults
 * and how to turn the field values into a step. Keeping it as data means the
 * panel renders whatever is here without a branch per trigger, and the same
 * catalogue can label a rule someone else built.
 */
export interface TriggerField {
  key: string
  label: string
  kind: "number" | "choice"
  step?: number
  min?: number
  max?: number
  choices?: { value: string; label: string }[]
}

export interface TriggerDef {
  id: string
  label: string
  group: "Indicators" | "Candles" | "Structure"
  fields: TriggerField[]
  defaults: Record<string, string | number>
  build: (values: Record<string, string | number>) => SequenceStep
}

const CROSS: TriggerField = {
  key: "cross",
  label: "Direction",
  kind: "choice",
  choices: [
    { value: "above", label: "crosses above" },
    { value: "below", label: "crosses below" },
  ],
}

const num = (key: string, label: string, step = 1, min = 1, max = 400): TriggerField => ({
  key, label, kind: "number", step, min, max,
})

export const TRIGGERS: TriggerDef[] = [
  {
    id: "ema_cross",
    label: "EMA cross",
    group: "Indicators",
    fields: [num("fast", "Fast EMA (1 = price)"), num("slow", "Slow EMA"), CROSS],
    defaults: { fast: 20, slow: 50, cross: "above" },
    build: (v) => ({ type: "ema_cross", fast: Number(v.fast), slow: Number(v.slow), cross: v.cross as "above" | "below" }),
  },
  {
    id: "macd_cross",
    label: "MACD cross",
    group: "Indicators",
    fields: [
      { key: "against", label: "Against", kind: "choice", choices: [
        { value: "signal", label: "its signal line" }, { value: "zero", label: "zero" }] },
      CROSS,
    ],
    defaults: { against: "signal", cross: "above" },
    build: (v) => ({ type: "macd_cross", fast: 12, slow: 26, signal: 9, against: v.against as "signal" | "zero", cross: v.cross as "above" | "below" }),
  },
  {
    id: "rsi",
    label: "RSI level",
    group: "Indicators",
    fields: [num("period", "Period", 1, 2, 200), num("level", "Level", 1, 0, 100), CROSS],
    defaults: { period: 14, level: 30, cross: "above" },
    build: (v) => ({ type: "indicator", indicator: "rsi", period: Number(v.period), level: Number(v.level), cross: v.cross as "above" | "below" }),
  },
  {
    id: "stoch_cross",
    label: "Stochastic",
    group: "Indicators",
    fields: [
      { key: "against", label: "Against", kind: "choice", choices: [
        { value: "d", label: "its %D line" }, { value: "level", label: "a level" }] },
      num("level", "Level", 1, 0, 100),
      CROSS,
    ],
    defaults: { against: "level", level: 20, cross: "above" },
    build: (v) => ({ type: "stoch_cross", k: 14, k_smooth: 3, d: 3, against: v.against as "d" | "level", level: Number(v.level), cross: v.cross as "above" | "below" }),
  },
  {
    id: "bollinger",
    label: "Bollinger band",
    group: "Indicators",
    fields: [
      { key: "band", label: "Band", kind: "choice", choices: [
        { value: "upper", label: "upper" }, { value: "middle", label: "middle" }, { value: "lower", label: "lower" }] },
      CROSS,
      num("period", "Period", 1, 2, 400),
    ],
    defaults: { band: "upper", cross: "above", period: 20 },
    build: (v) => ({ type: "bollinger", band: v.band as "upper" | "middle" | "lower", cross: v.cross as "above" | "below", period: Number(v.period), std: 2 }),
  },
  {
    id: "bollinger_squeeze",
    label: "Bollinger squeeze",
    group: "Indicators",
    fields: [num("period", "Period", 1, 2, 400), num("lookback", "Tightest in (bars)", 10, 10, 1000)],
    defaults: { period: 20, lookback: 120 },
    build: (v) => ({ type: "bollinger_squeeze", period: Number(v.period), std: 2, lookback: Number(v.lookback) }),
  },
  {
    id: "vwap_cross",
    label: "VWAP cross",
    group: "Indicators",
    fields: [
      { key: "anchor", label: "Anchored to", kind: "choice", choices: [
        { value: "day", label: "the UTC day" }, { value: "week", label: "the week" }] },
      CROSS,
    ],
    defaults: { anchor: "day", cross: "above" },
    build: (v) => ({ type: "vwap_cross", anchor: v.anchor as "day" | "week", cross: v.cross as "above" | "below" }),
  },
  {
    id: "volume_spike",
    label: "Volume spike",
    group: "Indicators",
    fields: [num("multiple", "Times its average", 0.5, 1.1, 50), num("period", "Average over", 1, 2, 400)],
    defaults: { multiple: 2, period: 20 },
    build: (v) => ({ type: "volume_spike", multiple: Number(v.multiple), period: Number(v.period) }),
  },
  {
    id: "atr_expansion",
    label: "Range expansion",
    group: "Indicators",
    fields: [num("multiple", "Times ATR", 0.5, 1.1, 20), num("period", "ATR period", 1, 2, 200)],
    defaults: { multiple: 2, period: 14 },
    build: (v) => ({ type: "atr_expansion", multiple: Number(v.multiple), period: Number(v.period) }),
  },
  {
    id: "candle",
    label: "Candle shape",
    group: "Candles",
    fields: [
      { key: "shape", label: "Shape", kind: "choice", choices: [
        { value: "doji", label: "doji" },
        { value: "hammer", label: "hammer" },
        { value: "shooting_star", label: "shooting star" },
        { value: "bullish_engulfing", label: "bullish engulfing" },
        { value: "bearish_engulfing", label: "bearish engulfing" },
        { value: "inside_bar", label: "inside bar" }] },
    ],
    defaults: { shape: "doji" },
    build: (v) => ({ type: "candle", shape: v.shape as "doji" }),
  },
  {
    id: "structure",
    label: "Structure event",
    group: "Structure",
    fields: [
      { key: "event", label: "Event", kind: "choice", choices: [
        { value: "sweep", label: "liquidity sweep" },
        { value: "breakout", label: "breakout" },
        { value: "rejection", label: "rejection" },
        { value: "pullback", label: "pullback" }] },
      { key: "side", label: "Side", kind: "choice", choices: [
        { value: "bullish", label: "bullish" }, { value: "bearish", label: "bearish" }] },
    ],
    defaults: { event: "sweep", side: "bullish" },
    build: (v) => ({ type: "structure", event: v.event as "sweep", side: v.side as "bullish" | "bearish" }),
  },
]

export function triggerById(id: string): TriggerDef | undefined {
  return TRIGGERS.find((t) => t.id === id)
}

/**
 * Bars a step needs before it can be judged, mirroring the server's
 * step_warmup. The server refuses a rule whose lookback cannot cover its
 * step, and a refusal the user could not have avoided is a bug here.
 */
export function stepWarmup(step: SequenceStep): number {
  switch (step.type) {
    case "indicator":
      return (step.period ?? 14) + 1
    case "ema_cross":
      return step.slow
    case "macd_cross":
      return (step.slow ?? 26) + (step.signal ?? 9)
    case "stoch_cross":
      return (step.k ?? 14) + (step.k_smooth ?? 3) + (step.d ?? 3)
    case "bollinger":
      return step.period ?? 20
    case "bollinger_squeeze":
      return (step.period ?? 20) + (step.lookback ?? 120)
    case "volume_spike":
      return (step.period ?? 20) + 1
    case "atr_expansion":
      return (step.period ?? 14) + 2
    default:
      return 2
  }
}

export function triggerName(def: TriggerDef, values: Record<string, string | number>): string {
  if (def.id === "candle") return String(values.shape).replace(/_/g, " ")
  if (def.id === "structure") return `${values.side} ${values.event}`
  return def.label
}

/** The params of a one-step sequence rule for this trigger. */
export function signalParams(
  def: TriggerDef,
  values: Record<string, string | number>,
): SequenceRuleParams {
  const step = def.build(values)
  const within = 3
  return {
    agent: "sequence",
    steps: [step],
    within_bars: within,
    lookback: Math.max(300, stepWarmup(step) + within + 2),
  }
}
