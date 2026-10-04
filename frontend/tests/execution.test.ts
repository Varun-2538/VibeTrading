import { describe, expect, it } from "vitest"
import {
  accountSummary,
  fmtR,
  fmtUsd,
  healthTrouble,
  marketForSymbol,
  marketsForSymbol,
  MARKET_CHAIN,
  MARKETS,
  refusalLines,
  type ExecutionAccount,
  type ExecutionHealth,
} from "@/lib/execution"

function account(over: Partial<ExecutionAccount> = {}): ExecutionAccount {
  return {
    owner_key: "0xabc", configured: true, mode: "off", kill_switch: false, equity_usd: 0,
    max_notional_usd: 100, max_concurrent_positions: 1, max_trades_per_day: 5,
    daily_loss_limit_usd: 25, halted_reason: null, execution_enabled: false, parity_version: 1,
    operator_address: null,
    ...over,
  }
}

function health(over: Partial<ExecutionHealth> = {}): ExecutionHealth {
  return {
    execution_enabled: true, globally_halted: null, mode: "shadow", kill_switch: false,
    halted_reason: null, parity_version: 1, queued: 0, stuck_intents: 0, orders_in_doubt: 0,
    open_positions: 0,
    ...over,
  }
}

describe("what the panel says about an account", () => {
  it("names the missing half rather than reporting a mode", () => {
    // "Armed" and "running" are different states, and the gap between them is the
    // most confusing thing about this feature.
    expect(accountSummary(account({ mode: "off", execution_enabled: false }))).toContain(
      "switched off, here and on the server",
    )
    expect(accountSummary(account({ mode: "shadow", execution_enabled: false }))).toContain(
      "switched off on the server",
    )
    expect(accountSummary(account({ mode: "off", execution_enabled: true }))).toContain("your account is off")
  })

  it("says plainly what shadow mode does", () => {
    expect(accountSummary(account({ mode: "shadow", execution_enabled: true }))).toContain("none is sent")
  })

  it("quotes the caps when it is live", () => {
    const line = accountSummary(account({ mode: "live", execution_enabled: true, max_notional_usd: 50 }))
    expect(line).toContain("$50")
    expect(line).toContain("5 trades a day")
  })

  it("puts a halt and a kill switch ahead of everything else", () => {
    expect(accountSummary(account({ mode: "live", execution_enabled: true, halted_reason: "unexplained position" })))
      .toContain("Nothing new will open")
    // And says the part people get wrong: a kill switch does not trap a position.
    expect(accountSummary(account({ mode: "live", execution_enabled: true, kill_switch: true })))
      .toContain("Open positions can still close")
  })

  it("asks for a wallet when there is no account at all", () => {
    expect(accountSummary(null)).toContain("Sign in")
  })
})

describe("whether something is wrong or nothing has happened", () => {
  it("is quiet when the queue is simply empty", () => {
    expect(healthTrouble(health())).toBeNull()
    expect(healthTrouble(health({ queued: 3 }))).toBeNull()
  })

  it("surfaces an unknown outcome, which is the one state a person must chase", () => {
    expect(healthTrouble(health({ orders_in_doubt: 2 }))).toContain("unknown")
    expect(healthTrouble(health({ stuck_intents: 1 }))).toContain("unfinished")
  })

  it("puts a server-wide halt above an account halt", () => {
    expect(healthTrouble(health({ globally_halted: "operator brake", halted_reason: "mine" })))
      .toContain("server-wide")
  })
})

describe("refusals", () => {
  it("renders every reason, not the first", () => {
    const result = { passed: false, reasons: ["too few trades", "a pool cannot short"], evidence: {} }
    expect(refusalLines(result)).toHaveLength(2)
  })

  it("has nothing to show when the gate passed", () => {
    expect(refusalLines({ passed: true, reasons: [], evidence: {} })).toEqual([])
    expect(refusalLines(null)).toEqual([])
  })
})

describe("formatting", () => {
  it("prints dollars and R the way the rest of the app does", () => {
    expect(fmtUsd(1234.5)).toBe("$1,234.5")
    expect(fmtUsd(null)).toBe("—")
    expect(fmtR(0.35)).toBe("+0.35R")
    expect(fmtR(-1)).toBe("-1.00R")
    expect(fmtR(null)).toBe("—")
  })
})

describe("markets", () => {
  it("mirrors the three the factories deploy vaults for", () => {
    expect(MARKETS).toEqual(["WETH/USDC", "WBTC/USDC", "WETH/USDG"])
  })

  it("names each market's chain by its dollar", () => {
    expect(MARKET_CHAIN["WETH/USDG"].key).toBe("robinhood")
    expect(MARKET_CHAIN["WETH/USDC"].key).toBe("arbitrum")
    expect(MARKET_CHAIN["WBTC/USDC"].key).toBe("arbitrum")
  })
})

describe("which rules can trade at all", () => {
  it("maps a symbol to every market a vault exists for, Robinhood Chain first", () => {
    expect(marketsForSymbol("ETHUSDT")).toEqual(["WETH/USDG", "WETH/USDC"])
    expect(marketForSymbol("ETHUSDT")).toBe("WETH/USDG")
    expect(marketsForSymbol("BTCUSDT")).toEqual(["WBTC/USDC"])
    expect(marketForSymbol("btcusdt")).toBe("WBTC/USDC")
  })

  it("refuses the pairs with no pool and no feed", () => {
    // A vault needs a deep Uniswap pool and a Chainlink price. Seven of the nine
    // pairs the app charts have neither, so a rule on them can alert forever and can
    // never be armed to trade - and the panel has to say that rather than fail later.
    for (const symbol of ["SOLUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", "DOTUSDT", "AVAXUSDT", "BNBUSDT"]) {
      expect(marketForSymbol(symbol)).toBeNull()
      expect(marketsForSymbol(symbol)).toEqual([])
    }
    expect(marketForSymbol("")).toBeNull()
  })
})
