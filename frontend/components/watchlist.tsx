"use client"

import { formatUsd, type Ticker } from "@/lib/binance"

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
 * The nine pairs the panel covers, priced live from Binance's 24h ticker.
 * Picking one switches the chart; it is the same state the symbol select sets.
 */
export default function Watchlist({
  tickers,
  selected,
  onSelect,
}: {
  tickers: Record<string, Ticker>
  selected: string
  onSelect: (symbol: string) => void
}) {
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
          const active = symbol === selected
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
    </section>
  )
}
