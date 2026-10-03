"use client"

/*
 * Draws what the chart fellow asked to mark.
 *
 * Additive to the existing overlays: it owns its own price lines and its own
 * markers plugin, and never touches the levels rail or the W/M overlay. Three
 * drawing routes, chosen by what lightweight-charts does well natively:
 *
 *   hline    -> series.createPriceLine     (axis label, follows the scale)
 *   bar      -> createSeriesMarkers        (anchored to a candle, survives pans)
 *   polyline -> SVG, via the same coordinate mapping the pattern overlay uses
 *   box      -> SVG
 */

import { useCallback, useEffect, useRef, useState } from "react"
import {
  createSeriesMarkers,
  LineStyle,
  type IChartApi,
  type IPriceLine,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type SeriesMarker,
  type SeriesType,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts"

import type { Mark } from "@/lib/marks"

const MARK_COLOUR = "#e8c547"
const MARK_FILL = "rgba(232,197,71,0.10)"

interface MarkOverlayProps {
  chart: IChartApi | null
  series: ISeriesApi<SeriesType> | null
  marks: Mark[]
}

export default function MarkOverlay({ chart, series, marks }: MarkOverlayProps) {
  const svgRef = useRef<SVGSVGElement>(null)
  const priceLines = useRef<IPriceLine[]>([])
  const markers = useRef<ISeriesMarkersPluginApi<Time> | null>(null)
  const [, setTick] = useState(0)

  const redraw = useCallback(() => setTick((t) => t + 1), [])

  // Native drawings: price lines and bar markers.
  useEffect(() => {
    if (!series) return

    for (const line of priceLines.current) series.removePriceLine(line)
    priceLines.current = marks
      .filter((m): m is Extract<Mark, { type: "hline" }> => m.type === "hline")
      .map((m) =>
        series.createPriceLine({
          price: m.price,
          color: MARK_COLOUR,
          lineWidth: 1,
          lineStyle: LineStyle.LargeDashed,
          axisLabelVisible: true,
          title: m.label,
        }),
      )

    const barMarks: SeriesMarker<Time>[] = marks
      .filter((m): m is Extract<Mark, { type: "bar" }> => m.type === "bar")
      .map(
        (m): SeriesMarker<Time> => ({
          time: (m.time / 1000) as UTCTimestamp,
          position: m.position === "above" ? "aboveBar" : "belowBar",
          shape: m.shape,
          color: MARK_COLOUR,
          text: m.text,
        }),
      )
      // The plugin requires ascending time.
      .sort((a, b) => (a.time as number) - (b.time as number))

    if (!markers.current) markers.current = createSeriesMarkers(series, barMarks)
    else markers.current.setMarkers(barMarks)

    return () => {
      for (const line of priceLines.current) series.removePriceLine(line)
      priceLines.current = []
      // The plugin belongs to this series; a swapped series gets a new one.
      markers.current?.detach()
      markers.current = null
    }
  }, [series, marks])

  // SVG drawings re-read their coordinates whenever the view moves.
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

  const svgMarks = marks.filter((m) => m.type === "polyline" || m.type === "box")
  if (!chart || !series || svgMarks.length === 0) {
    return <svg ref={svgRef} className="pointer-events-none absolute inset-0 z-10 h-full w-full" />
  }

  const timeScale = chart.timeScale()
  const x = (time: number) => timeScale.timeToCoordinate((time / 1000) as UTCTimestamp)
  const y = (price: number) => series.priceToCoordinate(price)

  return (
    <svg
      ref={svgRef}
      className="pointer-events-none absolute inset-0 z-10 h-full w-full overflow-visible"
      aria-hidden
    >
      {svgMarks.map((mark, i) => {
        if (mark.type === "polyline") {
          const coords = mark.points.map((p) => ({ x: x(p.time), y: y(p.price) }))
          if (coords.some((c) => c.x === null || c.y === null)) return null
          const pts = coords.map((c) => `${c.x},${c.y}`).join(" ")
          const last = coords[coords.length - 1]
          return (
            <g key={`poly-${i}`}>
              <polyline points={pts} fill="none" stroke={MARK_COLOUR} strokeWidth={1.5} />
              {coords.map((c, j) => (
                <circle key={j} cx={c.x as number} cy={c.y as number} r={3} fill={MARK_COLOUR} />
              ))}
              {mark.label && (
                <text
                  x={(last.x as number) + 6}
                  y={(last.y as number) - 6}
                  fill={MARK_COLOUR}
                  fontSize={11}
                  fontFamily="ui-monospace, monospace"
                >
                  {mark.label}
                </text>
              )}
            </g>
          )
        }

        const x1 = x(mark.from)
        const x2 = x(mark.to)
        const yTop = y(mark.price_top)
        const yBottom = y(mark.price_bottom)
        if (x1 === null || x2 === null || yTop === null || yBottom === null) return null
        return (
          <g key={`box-${i}`}>
            <rect
              x={Math.min(x1, x2)}
              y={Math.min(yTop, yBottom)}
              width={Math.abs(x2 - x1)}
              height={Math.abs(yBottom - yTop)}
              fill={MARK_FILL}
              stroke={MARK_COLOUR}
              strokeWidth={1}
              strokeDasharray="4 3"
            />
            {mark.label && (
              <text
                x={Math.min(x1, x2) + 4}
                y={Math.min(yTop, yBottom) - 4}
                fill={MARK_COLOUR}
                fontSize={11}
                fontFamily="ui-monospace, monospace"
              >
                {mark.label}
              </text>
            )}
          </g>
        )
      })}
    </svg>
  )
}
