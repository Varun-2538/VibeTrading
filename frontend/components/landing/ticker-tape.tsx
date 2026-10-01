"use client"

import { useEffect, useState } from "react"
import { formatUsd, subscribeTickers, type Ticker } from "@/lib/binance"

const SYMBOLS = [
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

const LABEL: Record<string, string> = {
  BTCUSDT: "BTC",
  ETHUSDT: "ETH",
  SOLUSDT: "SOL",
  BNBUSDT: "BNB",
  XRPUSDT: "XRP",
  ADAUSDT: "ADA",
  DOGEUSDT: "DOGE",
  AVAXUSDT: "AVAX",
  DOTUSDT: "DOT",
}

/** The nine pairs the app actually covers, priced live. */
export default function TickerTape() {
  const [quotes, setQuotes] = useState<Record<string, Ticker>>({})

  useEffect(
    () => subscribeTickers(SYMBOLS, (t) => setQuotes((prev) => ({ ...prev, [t.symbol]: t }))),
    [],
  )

  const ready = SYMBOLS.filter((s) => quotes[s])
  if (!ready.length) return <div className="h-[42px]" />

  const row = ready.map((s) => {
    const q = quotes[s]
    const up = q.changePct >= 0
    return (
      <span key={s} className="inline-flex items-baseline gap-2 px-6 font-mono text-xs">
        <span style={{ color: "var(--vt-ink-dim)" }}>{LABEL[s]}</span>
        <span style={{ color: "var(--vt-ink)" }}>{formatUsd(q.price)}</span>
        <span style={{ color: up ? "var(--vt-mint)" : "var(--vt-ink-faint)" }}>
          {up ? "+" : ""}
          {q.changePct.toFixed(2)}%
        </span>
      </span>
    )
  })

  return (
    <div
      className="relative overflow-hidden border-y py-3"
      style={{ borderColor: "var(--vt-line)" }}
    >
      <div
        className="vt-tape-track flex w-max"
        style={{ animation: "vt-tape 48s linear infinite" }}
      >
        <div className="flex shrink-0">{row}</div>
        <div className="flex shrink-0" aria-hidden>
          {row}
        </div>
      </div>
      {/* Fade the tape into the page rather than letting it hard-clip */}
      <div
        className="pointer-events-none absolute inset-y-0 left-0 w-24"
        style={{ background: "linear-gradient(to right, var(--vt-void), transparent)" }}
      />
      <div
        className="pointer-events-none absolute inset-y-0 right-0 w-24"
        style={{ background: "linear-gradient(to left, var(--vt-void), transparent)" }}
      />
    </div>
  )
}
