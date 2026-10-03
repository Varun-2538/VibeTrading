/**
 * Marks the chart fellow can ask the chart to draw, mirrored from
 * backend/models/fellow_schemas.py.
 *
 * Every mark that reaches the browser has already passed the server's
 * grounding guard: its prices and bar times were copied from detector output
 * for the window on screen. The chart draws them without re-checking.
 */

export interface HLineMark {
  type: "hline"
  price: number
  label: string
}

export interface BarMark {
  type: "bar"
  /** Bar open time, unix ms. */
  time: number
  position: "above" | "below"
  shape: "circle" | "arrowUp" | "arrowDown" | "square"
  text: string
}

export interface PolylineMark {
  type: "polyline"
  points: { time: number; price: number }[]
  label: string
}

export interface BoxMark {
  type: "box"
  from: number
  to: number
  price_top: number
  price_bottom: number
  label: string
}

export type Mark = HLineMark | BarMark | PolylineMark | BoxMark

export interface Finding {
  kind: "level" | "pattern" | "candle" | "indicator" | "structure"
  label: string
  present: boolean
  confidence: number
  why: string
  marks: Mark[]
  /** False when the server dropped marks the detectors could not vouch for. */
  grounded: boolean
}

export interface FellowAnswer {
  reply_md: string
  findings: Finding[]
  not_visible: string[]
}

export interface ChatTurn {
  role: "user" | "assistant"
  content: string
}

export interface Viewport {
  from: number
  to: number
}

export interface PatternSettings {
  strictness: string
  source: string
  scale: string
}

/** A stable identity for a mark, so toggling one on and off is idempotent. */
export function markKey(mark: Mark): string {
  switch (mark.type) {
    case "hline":
      return `hline:${mark.price}`
    case "bar":
      return `bar:${mark.time}:${mark.position}`
    case "polyline":
      return `poly:${mark.points.map((p) => `${p.time}@${p.price}`).join(",")}`
    case "box":
      return `box:${mark.from}:${mark.to}:${mark.price_top}:${mark.price_bottom}`
  }
}
