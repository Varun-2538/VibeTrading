"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import {
  LineStyle,
  type IChartApi,
  type IPriceLine,
  type ISeriesApi,
  type SeriesType,
  type UTCTimestamp,
} from "lightweight-charts"

import type { OpenPosition } from "@/lib/positions"

const ENTRY = "#d8e5e1"
const TP = "#7af0ce"
const SL = "#ff7a59"

function pct(from: number, to: number): string {
  const v = (to / from - 1) * 100
  return `${v >= 0 ? "+" : ""}${v.toFixed(1)}%`
}

/**
 * An open position drawn the way a trading terminal draws one: entry, take-profit
 * and stop-loss as labelled price lines, and the reward and risk zones shaded from
 * the bar it opened on. The levels are the vault's own, so what is drawn is exactly
 * what the contract will act on.
 */
export default function PositionOverlay({
  chart,
  series,
  positions,
  timeframeSeconds,
}: {
  chart: IChartApi | null
  series: ISeriesApi<SeriesType> | null
  positions: OpenPosition[]
  timeframeSeconds: number
}) {
  const svgRef = useRef<SVGSVGElement>(null)
  const lines = useRef<IPriceLine[]>([])
  const [, setTick] = useState(0)
  const redraw = useCallback(() => setTick((t) => t + 1), [])

  useEffect(() => {
    if (!series) return
    for (const line of lines.current) series.removePriceLine(line)
    lines.current = positions.flatMap((p) => {
      const out = [
        series.createPriceLine({
          price: p.entry,
          color: ENTRY,
          lineWidth: 1,
          lineStyle: LineStyle.Solid,
          axisLabelVisible: true,
          title: `Entry · ${p.label}`,
        }),
        series.createPriceLine({
          price: p.stop,
          color: SL,
          lineWidth: 2,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: true,
          title: `SL ${pct(p.entry, p.stop)}`,
        }),
      ]
      if (p.target !== null) {
        out.push(
          series.createPriceLine({
            price: p.target,
            color: TP,
            lineWidth: 2,
            lineStyle: LineStyle.Dashed,
            axisLabelVisible: true,
            title: `TP ${pct(p.entry, p.target)}`,
          }),
        )
      }
      return out
    })
    return () => {
      for (const line of lines.current) {
        try {
          series.removePriceLine(line)
        } catch {
          // The series went first.
        }
      }
      lines.current = []
    }
  }, [series, positions])

  useEffect(() => {
    if (!chart) return
    const timeScale = chart.timeScale()
    timeScale.subscribeVisibleLogicalRangeChange(redraw)
    const parent = svgRef.current?.parentElement
    const observer = parent ? new ResizeObserver(redraw) : null
    if (parent && observer) observer.observe(parent)
    return () => {
      timeScale.unsubscribeVisibleLogicalRangeChange(redraw)
      observer?.disconnect()
    }
  }, [chart, redraw])

  if (!chart || !series || positions.length === 0) {
    return <svg ref={svgRef} className="pointer-events-none absolute inset-0 z-10 h-full w-full" />
  }

  const timeScale = chart.timeScale()
  const right = timeScale.width()
  const y = (price: number) => series.priceToCoordinate(price)

  return (
    <svg ref={svgRef} className="pointer-events-none absolute inset-0 z-10 h-full w-full" aria-hidden>
      {positions.map((p) => {
        // The bar the position opened in; a time between bars has no coordinate.
        const bar = Math.floor(p.openedAt / timeframeSeconds) * timeframeSeconds
        const x = timeScale.timeToCoordinate(bar as UTCTimestamp) ?? 0
        const yEntry = y(p.entry)
        const yStop = y(p.stop)
        const yTarget = p.target !== null ? y(p.target) : null
        if (yEntry === null || x >= right) return null
        const left = Math.max(0, x)
        const width = right - left
        return (
          <g key={p.vault}>
            {yTarget !== null && (
              <rect
                x={left}
                y={Math.min(yEntry, yTarget)}
                width={width}
                height={Math.abs(yTarget - yEntry)}
                fill="rgba(122,240,206,0.10)"
              />
            )}
            {yStop !== null && (
              <rect
                x={left}
                y={Math.min(yEntry, yStop)}
                width={width}
                height={Math.abs(yStop - yEntry)}
                fill="rgba(255,122,89,0.10)"
              />
            )}
            <line x1={left} x2={left} y1={Math.min(yTarget ?? yEntry, yStop ?? yEntry)}
              y2={Math.max(yTarget ?? yEntry, yStop ?? yEntry)} stroke={ENTRY} strokeOpacity={0.35} strokeDasharray="2 3" />
          </g>
        )
      })}
    </svg>
  )
}
