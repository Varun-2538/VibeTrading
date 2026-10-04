"use client"

import { formatUsd, type Ticker } from "@/lib/binance"
import { STOCKS } from "@/lib/stocks"

export const WATCHLIST = [
  "BTCUSDT",
  "ETHUSDT",
  "SOLUSDT",
  "BNBUSDT",
  "XRPUSDT",
  "ADAUSDT",
  "DOGEUSDT",
  "AVAXUSDT",
  "DOTUSDT",
]

const compact = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 })

/**
 * The nine crypto pairs, priced live from Binance's 24h ticker, and Robinhood's
 * Stock Tokens, priced from their Uniswap pools on Robinhood Chain.
 * Picking one switches the chart; it is the same state the symbol select sets.
 */
export default function Watchlist({
  tickers,
  stockTickers = {},
  selected,
  onSelect,
  robinhoodEth = false,
}: {
  tickers: Record<string, Ticker>
  stockTickers?: Record<string, Ticker>
  selected: string
  onSelect: (symbol: string) => void
  /** ETH is on screen as Robinhood Chain's ETH/USDG, so that row is the active one. */
  robinhoodEth?: boolean
}) {
  const ethTicker = tickers["ETHUSDT"]
  const ethActive = robinhoodEth && selected === "ETHUSDT"
  const ethUp = (ethTicker?.changePct ?? 0) >= 0
  return (
    <section className="flex shrink-0 flex-col rounded-xl border border-border bg-card p-2">
      <div className="flex items-center justify-between px-1.5 pb-1.5 pt-0.5">
        <h2 className="font-mono text-[10px] font-semibold uppercase tracking-[0.08em] text-primary/80">
          Watchlist
        </h2>
        <span className="font-mono text-[10px] text-muted-foreground">24h · vol</span>
      </div>
      <ul className="flex flex-col gap-0.5">
        {WATCHLIST.map((symbol) => {
          const t = tickers[symbol]
          const active = symbol === selected && !(robinhoodEth && symbol === "ETHUSDT")
          const up = (t?.changePct ?? 0) >= 0
          return (
            <li key={symbol}>
              <button
                type="button"
                onClick={() => onSelect(symbol)}
                aria-current={active ? "true" : undefined}
                className={`flex w-full items-center justify-between rounded-lg px-2.5 py-2 text-left font-mono transition-colors ${
                  active ? "bg-secondary" : "hover:bg-muted"
                }`}
              >
                <span className="flex flex-col">
                  <span className={`flex items-center gap-1.5 text-[13px] ${active ? "font-bold text-primary" : "text-foreground"}`}>
                    {symbol}
                    {active && <span className="h-1 w-1 animate-pulse rounded-full bg-primary" />}
                  </span>
                  <span className="text-[11px] tabular-nums text-muted-foreground">
                    {t ? `$${formatUsd(t.price)}` : "—"}
                  </span>
                </span>
                <span className="flex flex-col items-end">
                  <span
                    className="text-[11px] font-medium tabular-nums"
                    style={{ color: t ? (up ? "#7af0ce" : "#ff7a59") : undefined }}
                  >
                    {t ? `${up ? "+" : ""}${t.changePct.toFixed(2)}%` : ""}
                  </span>
                  <span className="text-[11px] tabular-nums text-muted-foreground">
                    {t?.quoteVolume ? `$${compact.format(t.quoteVolume)}` : ""}
                  </span>
                </span>
              </button>
            </li>
          )
        })}
      </ul>
      <div className="flex items-center justify-between px-1.5 pb-1.5 pt-3">
        <h2 className="font-mono text-[10px] font-semibold uppercase tracking-[0.08em] text-primary/80">
          Robinhood Chain
        </h2>
        <span className="font-mono text-[10px] text-muted-foreground">24h</span>
      </div>
      <ul className="flex flex-col gap-0.5">
        <li>
          <button
            type="button"
            onClick={() => onSelect("ETHUSDG")}
            aria-current={ethActive ? "true" : undefined}
            className={`flex w-full items-center justify-between rounded-lg px-2.5 py-2 text-left font-mono transition-colors ${
              ethActive ? "bg-secondary" : "hover:bg-muted"
            }`}
          >
            <span className="flex flex-col">
              <span className={`flex items-center gap-1.5 text-[13px] ${ethActive ? "font-bold text-primary" : "text-foreground"}`}>
                ETH/USDG
                <span className="rounded bg-muted px-1 text-[9px] font-normal text-muted-foreground">VAULT</span>
                {ethActive && <span className="h-1 w-1 animate-pulse rounded-full bg-primary" />}
              </span>
              <span className="text-[11px] tabular-nums text-muted-foreground">
                {ethTicker ? `$${formatUsd(ethTicker.price)}` : "Ethereum"}
              </span>
            </span>
            <span
              className="text-[11px] font-medium tabular-nums"
              style={{ color: ethTicker ? (ethUp ? "#7af0ce" : "#ff7a59") : undefined }}
            >
              {ethTicker ? `${ethUp ? "+" : ""}${ethTicker.changePct.toFixed(2)}%` : ""}
            </span>
          </button>
        </li>
        {STOCKS.map((stock) => {
          const t = stockTickers[stock.symbol]
          const active = stock.symbol === selected
          const up = (t?.changePct ?? 0) >= 0
          return (
            <li key={stock.symbol}>
              <button
                type="button"
                onClick={() => onSelect(stock.symbol)}
                aria-current={active ? "true" : undefined}
                className={`flex w-full items-center justify-between rounded-lg px-2.5 py-2 text-left font-mono transition-colors ${
                  active ? "bg-secondary" : "hover:bg-muted"
                }`}
              >
                <span className="flex flex-col">
                  <span className={`flex items-center gap-1.5 text-[13px] ${active ? "font-bold text-primary" : "text-foreground"}`}>
                    {stock.symbol}
                    <span className="rounded bg-muted px-1 text-[9px] font-normal text-muted-foreground">STOCK</span>
                    {active && <span className="h-1 w-1 animate-pulse rounded-full bg-primary" />}
                  </span>
                  <span className="text-[11px] tabular-nums text-muted-foreground">
                    {t ? `$${formatUsd(t.price)}` : stock.name}
                  </span>
                </span>
                <span className="flex flex-col items-end">
                  <span
                    className="text-[11px] font-medium tabular-nums"
                    style={{ color: t ? (up ? "#7af0ce" : "#ff7a59") : undefined }}
                  >
                    {t ? `${up ? "+" : ""}${t.changePct.toFixed(2)}%` : ""}
                  </span>
                  <span className="text-[11px] tabular-nums text-muted-foreground">
                    {t?.quoteVolume ? `$${compact.format(t.quoteVolume)}` : ""}
                  </span>
                </span>
              </button>
            </li>
          )
        })}
      </ul>
    </section>
  )
}
