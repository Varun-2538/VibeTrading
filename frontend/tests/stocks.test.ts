import { describe, expect, it } from "vitest"
import {
  STOCKS,
  candlesUrl,
  isStock,
  parseCandles,
  parseQuotes,
  quotesUrl,
  stockFor,
} from "@/lib/stocks"
import { VAULT_MARKETS } from "@/lib/vault"

describe("the stock list", () => {
  it("charts exactly the tokens the stock vaults trade", () => {
    // A chart of one contract beside a vault of another would be a picture of the
    // wrong market. Every stock here must be a vault market with the same token.
    const vaultStocks = VAULT_MARKETS.filter((m) => m.stock)
    expect(STOCKS.map((s) => s.market).sort()).toEqual(vaultStocks.map((m) => m.market).sort())
    for (const s of STOCKS) {
      expect(vaultStocks.find((m) => m.market === s.market)?.asset).toBe(s.token)
    }
  })

  it("tells stocks from crypto pairs", () => {
    expect(isStock("NVDA")).toBe(true)
    expect(isStock("BTCUSDT")).toBe(false)
    expect(stockFor("TSLA")?.market).toBe("TSLA/USDG")
    expect(stockFor("DOGE")).toBeNull()
  })
})

describe("pool candles", () => {
  it("asks for the stock's own price, in dollars, at the chart's timeframe", () => {
    const nvda = stockFor("NVDA")!
    const url = candlesUrl(nvda, "4h")
    expect(url).toContain(`/networks/robinhood/pools/${nvda.pool}/ohlcv/hour?aggregate=4`)
    expect(url).toContain(`token=${nvda.token}`)
    expect(url).toContain("currency=usd")
    expect(candlesUrl(nvda, "15m")).toContain("/ohlcv/minute?aggregate=15")
    expect(candlesUrl(nvda, "1d")).toContain("/ohlcv/day?aggregate=1")
  })

  it("turns newest-first rows into oldest-first candles, without duplicates or junk", () => {
    const body = {
      data: {
        attributes: {
          ohlcv_list: [
            [3000, 3, 4, 2, 3.5, 30],
            [2000, 2, 3, 1, 2.5, 20],
            [2000, 2, 3, 1, 2.5, 20],
            [1000, 1, 2, 0.5, 1.5, 10],
            [500, null, 1, 1, 1, 1],
          ],
        },
      },
    }
    const candles = parseCandles(body)
    expect(candles.map((c) => c.time)).toEqual([1000, 2000, 3000])
    expect(candles[2]).toEqual({ time: 3000, open: 3, high: 4, low: 2, close: 3.5, volume: 30 })
    expect(parseCandles({})).toEqual([])
  })
})

describe("stock quotes", () => {
  it("asks for every pool in one request", () => {
    for (const s of STOCKS) expect(quotesUrl()).toContain(s.pool)
  })

  it("maps each pool back to its stock and ignores pools it does not know", () => {
    const nvda = stockFor("NVDA")!
    const body = {
      data: [
        {
          id: `robinhood_${nvda.pool}`,
          attributes: {
            base_token_price_usd: "234.78",
            price_change_percentage: { h24: "0.237" },
            volume_usd: { h24: "2166613.3" },
          },
        },
        { id: "robinhood_0xdeadbeef", attributes: { base_token_price_usd: "1" } },
        { id: `robinhood_${stockFor("TSLA")!.pool}`, attributes: { base_token_price_usd: "not a number" } },
      ],
    }
    const quotes = parseQuotes(body)
    expect(Object.keys(quotes)).toEqual(["NVDA"])
    expect(quotes.NVDA).toEqual({ symbol: "NVDA", price: 234.78, changePct: 0.237, quoteVolume: 2166613.3 })
  })
})
