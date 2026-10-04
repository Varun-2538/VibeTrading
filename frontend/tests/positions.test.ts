import { describe, expect, it } from "vitest"
import { chartSymbolFor, fromTuple, pnl, timeLeft } from "@/lib/positions"
import { vaultMarket } from "@/lib/vault"

const NVDA = vaultMarket("NVDA/USDG")!
const VAULT = "0x99a038f8335ADfb5332aCB8e4c520FaCCf8b99a5" as const

// The NVDA position opened on mainnet on 2026-10-04, as position() returned it.
const tuple = [
  true,
  BigInt(2_000_000),
  BigInt("8518908222029899"),
  BigInt(23_499_711_907),
  BigInt(21_149_740_716),
  BigInt(28_199_654_288),
  BigInt(1_791_092_728),
  BigInt(1_791_093_271),
] as const

describe("a vault's position, as the panel and the chart read it", () => {
  it("decodes prices from Chainlink's 8 decimals and the stake from USDG's 6", () => {
    const p = fromTuple(NVDA, VAULT, tuple)!
    expect(p.spentUsd).toBe(2)
    expect(p.entry).toBeCloseTo(234.997, 3)
    expect(p.stop).toBeCloseTo(211.497, 3)
    expect(p.target).toBeCloseTo(281.997, 3)
    expect(p.chartSymbol).toBe("NVDA")
    expect(p.deadline - p.openedAt).toBe(543)
  })

  it("is nothing when the vault is flat", () => {
    expect(fromTuple(NVDA, VAULT, [false, ...tuple.slice(1)] as unknown as typeof tuple)).toBeNull()
  })

  it("reads a zero target as no target", () => {
    const noTarget = [...tuple] as unknown as bigint[]
    noTarget[5] = BigInt(0)
    expect(fromTuple(NVDA, VAULT, noTarget as unknown as typeof tuple)!.target).toBeNull()
  })

  it("puts each market on the chart that shows it", () => {
    expect(chartSymbolFor(vaultMarket("WETH/USDG")!)).toBe("ETHUSDT")
    expect(chartSymbolFor(vaultMarket("WETH/USDC")!)).toBe("ETHUSDT")
    expect(chartSymbolFor(vaultMarket("WBTC/USDC")!)).toBe("BTCUSDT")
    expect(chartSymbolFor(NVDA)).toBe("NVDA")
  })

  it("prices a long's unrealised P&L off the entry", () => {
    const p = fromTuple(NVDA, VAULT, tuple)!
    const up = pnl(p, p.entry * 1.1)!
    expect(up.pct).toBeCloseTo(10, 6)
    expect(up.usd).toBeCloseTo(0.2, 6)
    expect(pnl(p, undefined)).toBeNull()
  })

  it("says how long is left on the time exit", () => {
    expect(timeLeft(1000, 1000)).toBe("due")
    expect(timeLeft(1000 + 9 * 60, 1000)).toBe("9m")
    expect(timeLeft(1000 + 3 * 3600 + 600, 1000)).toBe("3h 10m")
    expect(timeLeft(1000 + 2 * 86400 + 4 * 3600, 1000)).toBe("2d 4h")
  })
})
