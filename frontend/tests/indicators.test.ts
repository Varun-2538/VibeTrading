import { describe, expect, it } from "vitest"
import { ema, macd, parseIndicatorRequest, rsi, sma, specKey, withoutSpecs, withSpecs } from "@/lib/indicators"

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


const keys = (m: string) => parseIndicatorRequest(m).specs.map(specKey)

describe("reading what a chat message asks to draw", () => {
  it("averages a window", () => {
    expect(sma([1, 2, 3, 4], 2)).toEqual([null, 1.5, 2.5, 3.5])
  })

  it("reads EMA periods written either side of the word", () => {
    expect(keys("show EMA 9 and 21")).toEqual(["ema:9", "ema:21"])
    expect(keys("mark 9/21 ema crossover")).toEqual(["ema:9", "ema:21"])
    expect(keys("ema 9 aur ema 21 lagao")).toEqual(["ema:9", "ema:21"])
    expect(keys("add the 200 sma")).toEqual(["sma:200"])
  })

  it("reads RSI and MACD, with RSI's period when one is given", () => {
    expect(keys("show rsi")).toEqual(["rsi:14"])
    expect(keys("plot RSI(7) and macd")).toEqual(["rsi:7", "macd"])
  })

  it("answers a pure drawing request itself, and sends a question on to the assistant", () => {
    expect(parseIndicatorRequest("show EMA 9 and 21").drawOnly).toBe(true)
    expect(parseIndicatorRequest("Is there a MACD cross?").drawOnly).toBe(false)
    expect(keys("Is there a MACD cross?")).toEqual(["macd"])
    expect(parseIndicatorRequest("alert me when ema 9 crosses above ema 21").drawOnly).toBe(false)
  })

  it("does not read a bare 'ma' as an average", () => {
    expect(keys("mera ma ka chart")).toEqual([])
  })

  it("takes indicators off, a whole kind when no period is named", () => {
    const r = parseIndicatorRequest("remove ema")
    expect(r.remove).toBe(true)
    const on = withSpecs([], [{ kind: "ema", period: 9 }, { kind: "ema", period: 21 }, { kind: "macd" }])
    expect(withoutSpecs(on, r.specs).map(specKey)).toEqual(["macd"])
    expect(withoutSpecs(on, parseIndicatorRequest("hide ema 9").specs).map(specKey)).toEqual(["ema:21", "macd"])
  })
})
