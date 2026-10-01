"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import type { IChartApi, ISeriesApi, UTCTimestamp } from "lightweight-charts"
import { patternPoints, type Pattern, type PatternState } from "@/lib/api"

/*
 * Pattern geometry drawn over the chart canvas.
 *
 * Lightweight Charts can draw horizontal price lines but not the diagonal legs
 * of a W, so the shape is drawn in an SVG laid over the canvas and positioned
 * through the chart's own coordinate functions. Using those rather than our own
 * arithmetic is what keeps the drawing welded to the candles through panning,
 * zooming and resizing.
 *
 * The z-10 matters: Lightweight Charts puts its own canvases at z-index 1 and
 * 2, so an overlay left at the default stacking order draws perfectly and is
 * then painted over by the chart.
 */

const W_COLOUR = "#3987e5" // same blue as support: a W resolves upward
const M_COLOUR = "#d95926" // same orange as resistance: an M resolves downward

/**
 * How firmly each state is drawn.
 *
 * Prominence follows how much a pattern still matters, not how certain it is.
 * A pattern in its final approach is the only one that can still be acted on,
 * so it is drawn hardest; a break that happened hundreds of bars ago is
 * history and recedes into context. Drawing confirmed patterns boldest - the
 * obvious first instinct - filled the chart with emphatic marks about moves
 * that had already finished.
 *
 * Forming stays dashed and quiet because it is a guess, and dressing a guess
 * up as a finished call is the one thing this must not do.
 */
const STATE_STYLE: Record<
  PatternState,
  { opacity: number; width: number; dash: string }
> = {
  forming: { opacity: 0.55, width: 1.5, dash: "4 4" },
  approaching: { opacity: 1, width: 2.5, dash: "" },
  confirmed: { opacity: 0.45, width: 1.5, dash: "" },
}

interface PatternOverlayProps {
  chart: IChartApi | null
  series: ISeriesApi<"Candlestick"> | null
  patterns: Pattern[]
}

export default function PatternOverlay({ chart, series, patterns }: PatternOverlayProps) {
  const svgRef = useRef<SVGSVGElement>(null)
  // Bumped whenever the view moves, to force a re-read of the coordinates.
  const [, setTick] = useState(0)

  const redraw = useCallback(() => setTick((t) => t + 1), [])

  useEffect(() => {
    if (!chart) return

    const timeScale = chart.timeScale()
    timeScale.subscribeVisibleLogicalRangeChange(redraw)

    // The chart is autoSize, so it resizes without a window resize event.
    const parent = svgRef.current?.parentElement
    const observer = parent ? new ResizeObserver(redraw) : null
    if (parent && observer) observer.observe(parent)

    return () => {
      timeScale.unsubscribeVisibleLogicalRangeChange(redraw)
      observer?.disconnect()
    }
  }, [chart, redraw])

  if (!chart || !series || patterns.length === 0) {
    return <svg ref={svgRef} className="pointer-events-none absolute inset-0 z-10 h-full w-full" />
  }

  const timeScale = chart.timeScale()
  const x = (time: number) => timeScale.timeToCoordinate((time / 1000) as UTCTimestamp)
  const y = (price: number) => series.priceToCoordinate(price)

  // Only the most recent completed pattern is annotated. Patterns arrive
  // ranked, so this is the first confirmed one in the list. Labelling every
  // completed pattern stacked text and target lines on top of each other until
  // none of it could be read.
  const primaryConfirmed = patterns.findIndex((p) => p.state === "confirmed")

  return (
    <svg
      ref={svgRef}
      className="pointer-events-none absolute inset-0 z-10 h-full w-full overflow-visible"
      aria-hidden
    >
      {patterns.map((pattern, index) => {
        const points = patternPoints(pattern)
        const coords = points.map((p) => ({ x: x(p.time), y: y(p.price) }))

        // A point scrolled outside the visible range has no coordinate. Skip
        // the whole pattern rather than drawing a partial, misleading shape.
        if (coords.some((c) => c.x === null || c.y === null)) return null

        const style = STATE_STYLE[pattern.state]
        const colour = pattern.kind === "W" ? W_COLOUR : M_COLOUR
        const annotated =
          pattern.state !== "confirmed" ? pattern.state === "approaching" : index === primaryConfirmed
        const neckY = y(pattern.neckline)
        const targetY = y(pattern.target)

        const legs = coords.map((c) => `${c.x},${c.y}`).join(" ")
        const firstX = coords[0].x as number
        const lastX = coords[coords.length - 1].x as number
        const apexY = coords[1].y as number

        return (
          <g key={`${pattern.kind}-${points[0].time}-${index}`} opacity={style.opacity}>
            {/* The legs of the W or M */}
            <polyline
              points={legs}
              fill="none"
              stroke={colour}
              strokeWidth={style.width}
              strokeDasharray={style.dash}
              strokeLinejoin="round"
            />

            {/* Shoulders */}
            {coords.map((c, i) =>
              i === 1 ? null : (
                <circle key={i} cx={c.x as number} cy={c.y as number} r={3} fill={colour} />
              ),
            )}

            {/* Neckline, extended a little past the pattern to show the level
                price has to clear. */}
            {neckY !== null && (
              <line
                x1={firstX}
                y1={neckY}
                x2={lastX + 60}
                y2={neckY}
                stroke={colour}
                strokeWidth={1}
                strokeDasharray="6 4"
              />
            )}

            {/* Measured move, only once the break has actually happened -
                showing a target for a pattern that may never complete would
                promise something the analysis does not support. */}
            {pattern.state === "confirmed" && annotated && targetY !== null && (
              <>
                <line
                  x1={lastX}
                  y1={targetY}
                  x2={lastX + 60}
                  y2={targetY}
                  stroke={colour}
                  strokeWidth={1}
                  strokeDasharray="2 3"
                />
                <text
                  x={lastX + 64}
                  y={targetY + 3}
                  fill={colour}
                  fontSize={10}
                  fontFamily="ui-monospace, monospace"
                >
                  target
                </text>
              </>
            )}

            {annotated && (
              <text
                x={(firstX + lastX) / 2}
                y={apexY + (pattern.kind === "W" ? -8 : 16)}
                fill={colour}
                fontSize={11}
                fontWeight={600}
                textAnchor="middle"
                fontFamily="ui-monospace, monospace"
              >
                {pattern.kind} {pattern.state} {Math.round(pattern.confidence)}%
              </text>
            )}
          </g>
        )
      })}
    </svg>
  )
}
