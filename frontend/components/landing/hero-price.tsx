"use client"

import { useEffect, useState } from "react"
import { formatUsd, subscribeTickers, type Ticker } from "@/lib/binance"

/**
 * The eyebrow is the live BTC print rather than a tagline. It is the first
 * thing on the page and it is already moving, which is the whole claim.
 */
export default function HeroPrice() {
  const [btc, setBtc] = useState<Ticker | null>(null)
  const [flash, setFlash] = useState(false)

  useEffect(
    () =>
      subscribeTickers(["BTCUSDT"], (t) => {
        setBtc((prev) => {
          if (prev && prev.price !== t.price) {
            setFlash(true)
            setTimeout(() => setFlash(false), 220)
          }
          return t
        })
      }),
    [],
  )

  return (
    <div className="flex h-6 items-center gap-3 font-mono text-xs">
      <span className="flex items-center gap-2">
        <span
          className={`inline-block h-1.5 w-1.5 rounded-full ${btc ? "animate-pulse" : ""}`}
          style={{ background: btc ? "var(--vt-mint)" : "var(--vt-ink-faint)" }}
        />
        <span className="uppercase tracking-[0.18em]" style={{ color: "var(--vt-ink-faint)" }}>
          {btc ? "Live" : "Connecting"}
        </span>
      </span>

      {btc && (
        <>
          <span style={{ color: "var(--vt-ink-faint)" }}>BTC/USDT</span>
          <span
            className="transition-colors duration-200"
            style={{ color: flash ? "var(--vt-mint)" : "var(--vt-ink)" }}
          >
            ${formatUsd(btc.price)}
          </span>
          <span style={{ color: btc.changePct >= 0 ? "var(--vt-mint)" : "var(--vt-ink-dim)" }}>
            {btc.changePct >= 0 ? "+" : ""}
            {btc.changePct.toFixed(2)}%
          </span>
        </>
      )}
    </div>
  )
}
