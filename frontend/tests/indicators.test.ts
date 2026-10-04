import { describe, expect, it } from "vitest"
import { ema, macd, rsi } from "@/lib/indicators"

const rising = Array.from({ length: 60 }, (_, i) => 100 + i)
const zigzag = Array.from({ length: 60 }, (_, i) => 100 + (i % 2 === 0 ? 1 : -1))

describe("the indicators under the chart", () => {
  it("seeds an EMA with the simple mean and leaves the warm-up empty", () => {
    const e = ema([1, 2, 3, 4], 3)
    expect(e.slice(0, 2)).toEqual([null, null])
    expect(e[2]).toBe(2)
    expect(e[3]).toBe(3)
  })

  it("reads RSI as 100 when every bar closes higher, and near 50 when they alternate", () => {
    const up = rsi(rising)
    expect(up[13]).toBeNull()
    expect(up[14]).toBe(100)
    const flat = rsi(zigzag).at(-1)!
    expect(flat).toBeGreaterThan(40)
    expect(flat).toBeLessThan(60)
  })

  it("puts MACD above its signal in a steady rise and keeps histogram = macd - signal", () => {
    const m = macd(rising)
    expect(m[32]).toBeNull()
    const last = m.at(-1)!
    expect(last.macd).toBeGreaterThan(0)
    expect(last.histogram).toBeCloseTo(last.macd - last.signal, 10)
    expect(m.findIndex((v) => v !== null)).toBe(26 - 1 + 9 - 1)
  })
})
