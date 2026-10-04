"use client"

import { useEffect, useRef } from "react"
import {
  HistogramSeries,
  LineSeries,
  LineStyle,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
} from "lightweight-charts"

import { macd, rsi } from "@/lib/indicators"

export interface IndicatorToggles {
  rsi: boolean
  macd: boolean
}

export const DEFAULT_INDICATORS: IndicatorToggles = { rsi: true, macd: true }

const RSI_COLOR = "#b49cff"
const MACD_COLOR = "#7ab8ff"
const SIGNAL_COLOR = "#ffb35c"
const UP = "rgba(122,240,206,0.55)"
const DOWN = "rgba(255,122,89,0.55)"
const BAND = "rgba(216,229,225,0.35)"
const PANE_HEIGHT = 90

interface Bar {
  time: number // ms, or seconds with `timeInSeconds`
  close: number
}

interface Panes {
  rsi?: ISeriesApi<"Line">
  macd?: ISeriesApi<"Line">
  signal?: ISeriesApi<"Line">
  histogram?: ISeriesApi<"Histogram">
}

/**
 * RSI(14) and MACD(12, 26, 9) in their own panes under the price, sharing its
 * time axis. `candles` is read whenever `version` changes, so a caller that
 * mutates its candle array in place (a live tick) only has to bump the version.
 */
export function useIndicatorPanes(
  chart: IChartApi | null,
  candles: Bar[],
  version: number,
  show: IndicatorToggles,
  timeInSeconds = false,
) {
  const panes = useRef<Panes>({})

  // Build the series for whichever indicators are on; rebuilt on a toggle so the
  // panes stay packed under the price with no empty one between them.
  useEffect(() => {
    if (!chart) return
    const made: Panes = {}
    let pane = 1
    if (show.rsi) {
      made.rsi = chart.addSeries(
        LineSeries,
        { color: RSI_COLOR, lineWidth: 1, priceLineVisible: false, lastValueVisible: true, title: "RSI 14" },
        pane,
      )
      for (const level of [70, 30]) {
        made.rsi.createPriceLine({ price: level, color: BAND, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: false, title: "" })
      }
      pane += 1
    }
    if (show.macd) {
      made.histogram = chart.addSeries(HistogramSeries, { priceLineVisible: false, lastValueVisible: false }, pane)
      made.macd = chart.addSeries(
        LineSeries,
        { color: MACD_COLOR, lineWidth: 1, priceLineVisible: false, lastValueVisible: true, title: "MACD 12 26 9" },
        pane,
      )
      made.signal = chart.addSeries(
        LineSeries,
        { color: SIGNAL_COLOR, lineWidth: 1, priceLineVisible: false, lastValueVisible: false },
        pane,
      )
    }
    for (const p of chart.panes().slice(1)) p.setHeight(PANE_HEIGHT)
    panes.current = made
    return () => {
      for (const s of Object.values(made)) {
        try {
          chart.removeSeries(s)
        } catch {
          // The chart went first.
        }
      }
      panes.current = {}
    }
  }, [chart, show.rsi, show.macd])

  useEffect(() => {
    const p = panes.current
    if (!chart || candles.length === 0) return
    const closes = candles.map((c) => c.close)
    const t = (i: number) => (timeInSeconds ? candles[i].time : candles[i].time / 1000) as UTCTimestamp
    if (p.rsi) {
      const r = rsi(closes)
      p.rsi.setData(r.flatMap((v, i) => (v === null ? [] : [{ time: t(i), value: v }])))
    }
    if (p.macd && p.signal && p.histogram) {
      const m = macd(closes)
      const at = m.flatMap((v, i) => (v === null ? [] : [{ i, v }]))
      p.macd.setData(at.map(({ i, v }) => ({ time: t(i), value: v.macd })))
      p.signal.setData(at.map(({ i, v }) => ({ time: t(i), value: v.signal })))
      p.histogram.setData(at.map(({ i, v }) => ({ time: t(i), value: v.histogram, color: v.histogram >= 0 ? UP : DOWN })))
    }
  }, [chart, candles, version, show.rsi, show.macd, timeInSeconds])
}

/** Two small switches, styled like the chart's other toggles. */
export function IndicatorSwitches({
  value,
  onChange,
}: {
  value: IndicatorToggles
  onChange: (next: IndicatorToggles) => void
}) {
  return (
    <div className="flex shrink-0 items-center gap-1" role="group" aria-label="Indicators">
      {(["rsi", "macd"] as const).map((k) => (
        <button
          key={k}
          type="button"
          aria-pressed={value[k]}
          onClick={() => onChange({ ...value, [k]: !value[k] })}
          className={`h-9 rounded-md px-2 text-xs font-medium uppercase transition-colors lg:h-7 ${
            value[k] ? "bg-secondary text-foreground" : "text-muted-foreground hover:text-foreground"
          }`}
        >
          {k}
        </button>
      ))}
    </div>
  )
}
