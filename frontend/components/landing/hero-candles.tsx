"use client"

import { useEffect, useMemo, useState } from "react"
import { fetchKlines, subscribeKline, type Kline } from "@/lib/binance"

/**
 * The signature element: the real BTC market, live, behind the headline.
 *
 * Not decoration - it is the product's own subject matter. The horizontal
 * mint rules are clustered price levels computed the same way the app does
 * it, so the backdrop is literally a preview of what the tool outputs.
 */
export default function HeroCandles() {
  const [candles, setCandles] = useState<Kline[]>([])

  useEffect(() => {
    let alive = true
    fetchKlines("BTCUSDT", "1h", 90)
      .then((k) => alive && setCandles(k))
      .catch(() => {})
    return () => {
      alive = false
    }
  }, [])

  useEffect(() => {
    if (!candles.length) return
    return subscribeKline("BTCUSDT", "1h", (candle) => {
      setCandles((prev) => {
        if (!prev.length) return prev
        const last = prev[prev.length - 1]
        if (candle.time === last.time) {
          const next = prev.slice()
          next[next.length - 1] = candle
          return next
        }
        if (candle.time > last.time) return [...prev.slice(1), candle]
        return prev
      })
    })
  }, [candles.length > 0])

  const view = useMemo(() => {
    if (candles.length < 2) return null

    const W = 1200
    const H = 380
    const lows = candles.map((c) => c.low)
    const highs = candles.map((c) => c.high)
    const min = Math.min(...lows)
    const max = Math.max(...highs)
    const pad = (max - min) * 0.12 || 1
    const lo = min - pad
    const hi = max + pad

    const y = (p: number) => H - ((p - lo) / (hi - lo)) * H
    const step = W / candles.length
    const bodyW = Math.max(step * 0.58, 1.5)

    // Cluster highs and lows into levels, same idea as the backend detector.
    const prices = [...highs, ...lows]
    const clusters: { sum: number; n: number; ref: number }[] = []
    for (const p of prices) {
      const hit = clusters.find((c) => Math.abs(p - c.ref) / c.ref <= 0.012)
      if (hit) {
        hit.sum += p
        hit.n += 1
      } else {
        clusters.push({ sum: p, n: 1, ref: p })
      }
    }
    const levels = clusters
      .filter((c) => c.n >= 12)
      .map((c) => c.sum / c.n)
      .sort((a, b) => b - a)
      .slice(0, 3)

    return { W, H, y, step, bodyW, levels }
  }, [candles])

  if (!view) return null
  const { W, H, y, step, bodyW, levels } = view

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="none"
      className="vt-breathe h-full w-full"
      style={{ animation: "vt-breathe 7s ease-in-out infinite" }}
      aria-hidden
    >
      {levels.map((price, i) => (
        <line
          key={i}
          x1={0}
          x2={W}
          y1={y(price)}
          y2={y(price)}
          stroke="var(--vt-mint)"
          strokeWidth={1}
          strokeDasharray="2 9"
          opacity={0.5}
        />
      ))}

      {candles.map((c, i) => {
        const x = i * step + (step - bodyW) / 2
        const up = c.close >= c.open
        const top = y(Math.max(c.open, c.close))
        const height = Math.max(Math.abs(y(c.open) - y(c.close)), 1)
        const centre = x + bodyW / 2
        return (
          <g key={c.time}>
            <line
              x1={centre}
              x2={centre}
              y1={y(c.high)}
              y2={y(c.low)}
              stroke="var(--vt-ink-dim)"
              strokeWidth={0.75}
            />
            <rect
              x={x}
              y={top}
              width={bodyW}
              height={height}
              fill={up ? "transparent" : "var(--vt-ink-dim)"}
              stroke="var(--vt-ink-dim)"
              strokeWidth={0.75}
            />
          </g>
        )
      })}
    </svg>
  )
}
