import { describe, expect, it } from "vitest"
import {
  CURRENT_DISCLOSURE,
  DISCLOSURES,
  assetForMarket,
  disclosureHash,
  disclosureText,
  formatFeedPrice,
  formatUsdc,
  grantActive,
  grantExpiry,
  headroom,
  parseUsdc,
  toFeedPrice,
  VAULT_MARKETS,
} from "@/lib/vault"

describe("the disclosure a vault stores", () => {
  it("hashes the exact text, and the hash does not move", () => {
    // Pinned deliberately. A vault deployed today stores this hash forever, so if
    // this fails someone edited an accepted version instead of adding a new one -
    // and every vault that accepted v1 would now disagree with the site about what
    // its owner agreed to. Add v2; never edit v1.
    expect(disclosureHash("v1")).toBe("0xf70d3f54cf9085017e7415ce04350ab9aa25cc4d29fcf1d16f69f271edf6b47d")
    expect(disclosureHash(CURRENT_DISCLOSURE)).toBe(disclosureHash("v1"))
  })

  it("says the things the vault actually enforces", () => {
    const text = disclosureText()
    expect(text).toContain("cannot withdraw")
    expect(text).toContain("revoke")
    expect(text).toContain("not guaranteed fill prices")
  })

  it("refuses a version it has no text for", () => {
    expect(() => disclosureText("v99")).toThrow()
    expect(Object.keys(DISCLOSURES)).toContain(CURRENT_DISCLOSURE)
  })
})

describe("amounts", () => {
  it("reads and writes USDC's six decimals", () => {
    expect(parseUsdc("100")).toBe(100_000_000n)
    expect(parseUsdc("$1,234.56")).toBe(1_234_560_000n)
    expect(parseUsdc("0.000001")).toBe(1n)
    expect(formatUsdc(100_000_000n)).toBe("$100.00")
    expect(formatUsdc(1_234_567_890n)).toBe("$1,234.56")
    expect(formatUsdc(null)).toBe("—")
  })

  it("refuses anything it cannot represent exactly", () => {
    expect(parseUsdc("0.0000001")).toBeNull()
    expect(parseUsdc("abc")).toBeNull()
    expect(parseUsdc("")).toBeNull()
  })

  it("reads a Chainlink price at eight decimals", () => {
    expect(formatFeedPrice(2000_00000000n)).toBe("$2,000.00")
    expect(formatFeedPrice(0n)).toBe("—")
    expect(toFeedPrice(1850.5)).toBe(185_050_000_000n)
  })
})

describe("the grant we hold", () => {
  const now = new Date("2026-09-27T12:00:00Z")
  const seconds = BigInt(Math.floor(now.getTime() / 1000))

  it("is only active while it has not expired", () => {
    const operator = "0x000000000000000000000000000000000000dEaD" as const
    expect(grantActive({ operator, operatorExpiry: seconds + 100n }, now)).toBe(true)
    // An expired grant still reads as an address and refuses every call, so
    // "an operator is set" is the wrong question to ask the chain.
    expect(grantActive({ operator, operatorExpiry: seconds - 1n }, now)).toBe(false)
    expect(
      grantActive({ operator: "0x0000000000000000000000000000000000000000", operatorExpiry: seconds + 100n }, now),
    ).toBe(false)
  })

  it("expires a whole number of days out", () => {
    expect(grantExpiry(30, now)).toBe(seconds + 30n * 86_400n)
  })
})

describe("the hard cap", () => {
  it("reports the room left, and never a negative one", () => {
    expect(headroom({ balance: 100_000_000n, tvlCap: 500_000_000n })).toBe(400_000_000n)
    expect(headroom({ balance: 600_000_000n, tvlCap: 500_000_000n })).toBe(0n)
  })
})

describe("markets", () => {
  it("mirrors the factory's fixed list", () => {
    expect(VAULT_MARKETS.map((m) => m.market)).toEqual(["WETH/USDC", "WBTC/USDC"])
    expect(assetForMarket("WETH/USDC")).toMatch(/^0x[0-9a-fA-F]{40}$/)
    expect(assetForMarket("DOGE/USDC")).toBeNull()
  })
})
