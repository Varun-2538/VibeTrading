"use client"

import { useEffect, useRef, useState } from "react"
import {
  HistogramSeries,
  LineSeries,
  LineStyle,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
} from "lightweight-charts"
import { ChevronDown, ChevronLeft, ChevronRight, X } from "lucide-react"

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  DEFAULT_SPECS,
  INDICATOR_EVENT,
  PRESETS,
  ema,
  isOverlay,
  macd,
  rsi,
  sma,
  specKey,
  specLabel,
  withSpecs,
  withoutSpecs,
  type IndicatorEventDetail,
  type IndicatorSpec,
} from "@/lib/indicators"

const OVERLAY_COLORS = ["#ffd166", "#5ec8ff", "#ff8fd8", "#c3f584", "#f4f4f4", "#ff9f5c"]
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

type Drawn =
  | { spec: IndicatorSpec; line: ISeriesApi<"Line"> }
  | { spec: IndicatorSpec; macd: ISeriesApi<"Line">; signal: ISeriesApi<"Line">; histogram: ISeriesApi<"Histogram"> }

/** The colour an indicator is drawn in, shared by its line and its chip. */
export function colorOf(specs: IndicatorSpec[], s: IndicatorSpec): string {
  if (s.kind === "rsi") return RSI_COLOR
  if (s.kind === "macd") return MACD_COLOR
  const i = specs.filter(isOverlay).findIndex((o) => specKey(o) === specKey(s))
  return OVERLAY_COLORS[Math.max(0, i) % OVERLAY_COLORS.length]
}

/**
 * The chart's indicators as state, which the chat can also change: it sends
 * INDICATOR_EVENT when a message asks to draw (or remove) one.
 */
export function useChartIndicators(): [IndicatorSpec[], (next: IndicatorSpec[]) => void] {
  const [specs, setSpecs] = useState<IndicatorSpec[]>(DEFAULT_SPECS)
  useEffect(() => {
    const on = (e: Event) => {
      const d = (e as CustomEvent<IndicatorEventDetail>).detail ?? {}
      setSpecs((cur) => {
        let next = cur
        if (d.remove) next = withoutSpecs(next, d.remove)
        if (d.add) next = withSpecs(next, d.add)
        return next
      })
    }
    window.addEventListener(INDICATOR_EVENT, on)
    return () => window.removeEventListener(INDICATOR_EVENT, on)
  }, [])
  return [specs, setSpecs]
}

/**
 * Draw `specs`: moving averages on the price, RSI and MACD each in a pane under
 * it, all on the price's time axis. `candles` is read whenever `version` changes,
 * so a caller that mutates its candle array in place only has to bump the version.
 * The maths is the rule steps' maths, so the line a rule crosses is the one on screen.
 */
export function useIndicatorPanes(
  chart: IChartApi | null,
  candles: Bar[],
  version: number,
  specs: IndicatorSpec[],
  timeInSeconds = false,
) {
  const drawn = useRef<Drawn[]>([])
  const keys = specs.map(specKey).join("|")

  useEffect(() => {
    if (!chart) return
    const made: Drawn[] = []
    let pane = 1
    for (const s of specs) {
      if (isOverlay(s)) {
        made.push({
          spec: s,
          line: chart.addSeries(LineSeries, {
            color: colorOf(specs, s),
            lineWidth: 2,
            priceLineVisible: false,
            lastValueVisible: true,
            crosshairMarkerVisible: false,
            title: specLabel(s),
          }),
        })
      } else if (s.kind === "rsi") {
        const line = chart.addSeries(
          LineSeries,
          { color: RSI_COLOR, lineWidth: 1, priceLineVisible: false, lastValueVisible: true, title: specLabel(s) },
          pane++,
        )
        for (const level of [70, 30]) {
          line.createPriceLine({ price: level, color: BAND, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: false, title: "" })
        }
        made.push({ spec: s, line })
      } else {
        const at = pane++
        made.push({
          spec: s,
          histogram: chart.addSeries(HistogramSeries, { priceLineVisible: false, lastValueVisible: false }, at),
          macd: chart.addSeries(
            LineSeries,
            { color: MACD_COLOR, lineWidth: 1, priceLineVisible: false, lastValueVisible: true, title: specLabel(s) },
            at,
          ),
          signal: chart.addSeries(
            LineSeries,
            { color: SIGNAL_COLOR, lineWidth: 1, priceLineVisible: false, lastValueVisible: false },
            at,
          ),
        })
      }
    }
    for (const p of chart.panes().slice(1)) p.setHeight(PANE_HEIGHT)
    drawn.current = made
    return () => {
      for (const d of made) {
        const series = "line" in d ? [d.line] : [d.histogram, d.macd, d.signal]
        for (const s of series) {
          try {
            chart.removeSeries(s)
          } catch {
            // The chart went first.
          }
        }
      }
      drawn.current = []
    }
  }, [chart, keys]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!chart || candles.length === 0) return
    const closes = candles.map((c) => c.close)
    const t = (i: number) => (timeInSeconds ? candles[i].time : candles[i].time / 1000) as UTCTimestamp
    const line = (values: (number | null)[]) =>
      values.flatMap((v, i) => (v === null ? [] : [{ time: t(i), value: v }]))
    for (const d of drawn.current) {
      const s = d.spec
      if ("line" in d) {
        if (s.kind === "ema") d.line.setData(line(ema(closes, s.period)))
        else if (s.kind === "sma") d.line.setData(line(sma(closes, s.period)))
        else if (s.kind === "rsi") d.line.setData(line(rsi(closes, s.period)))
      } else {
        const at = macd(closes).flatMap((v, i) => (v === null ? [] : [{ i, v }]))
        d.macd.setData(at.map(({ i, v }) => ({ time: t(i), value: v.macd })))
        d.signal.setData(at.map(({ i, v }) => ({ time: t(i), value: v.signal })))
        d.histogram.setData(at.map(({ i, v }) => ({ time: t(i), value: v.histogram, color: v.histogram >= 0 ? UP : DOWN })))
      }
    }
  }, [chart, candles, version, keys, timeInSeconds])
}

/**
 * The indicator bar over the chart: a menu to add one, a chip with a cross for
 * each that is on, and a chevron that folds the chips away.
 */
export function IndicatorBar({
  specs,
  onChange,
}: {
  specs: IndicatorSpec[]
  onChange: (next: IndicatorSpec[]) => void
}) {
  const [open, setOpen] = useState(true)
  const [custom, setCustom] = useState("")
  const on = new Set(specs.map(specKey))
  const addCustom = (kind: "ema" | "sma") => {
    const p = Number(custom)
    if (Number.isInteger(p) && p >= 2 && p <= 400) {
      onChange(withSpecs(specs, [{ kind, period: p }]))
      setCustom("")
    }
  }

  return (
    <div className="pointer-events-auto flex max-w-full flex-wrap items-center gap-1">
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button
            type="button"
            className="flex h-6 items-center gap-1 rounded border border-border bg-background/90 px-2 text-[11px] font-medium text-foreground backdrop-blur hover:bg-secondary"
          >
            Indicators
            {specs.length > 0 && <span className="tabular-nums text-muted-foreground">{specs.length}</span>}
            <ChevronDown className="h-3 w-3" />
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="w-52">
          <DropdownMenuLabel className="text-[11px]">On the price</DropdownMenuLabel>
          {PRESETS.filter(isOverlay).map((s) => (
            <DropdownMenuItem
              key={specKey(s)}
              disabled={on.has(specKey(s))}
              onSelect={() => onChange(withSpecs(specs, [s]))}
              className="text-xs"
            >
              {specLabel(s)}
              {on.has(specKey(s)) && <span className="ml-auto text-[10px] text-muted-foreground">on</span>}
            </DropdownMenuItem>
          ))}
          <div className="flex items-center gap-1 px-2 py-1.5" onKeyDown={(e) => e.stopPropagation()}>
            <input
              value={custom}
              onChange={(e) => setCustom(e.target.value.replace(/\D/g, "").slice(0, 3))}
              placeholder="Period"
              inputMode="numeric"
              className="h-6 w-14 rounded border border-border bg-background px-1.5 text-xs"
            />
            <button type="button" onClick={() => addCustom("ema")} className="h-6 rounded bg-secondary px-2 text-[11px]">
              + EMA
            </button>
            <button type="button" onClick={() => addCustom("sma")} className="h-6 rounded bg-secondary px-2 text-[11px]">
              + SMA
            </button>
          </div>
          <DropdownMenuSeparator />
          <DropdownMenuLabel className="text-[11px]">Under the chart</DropdownMenuLabel>
          {PRESETS.filter((s) => !isOverlay(s)).map((s) => (
            <DropdownMenuItem
              key={specKey(s)}
              disabled={on.has(specKey(s))}
              onSelect={() => onChange(withSpecs(specs, [s]))}
              className="text-xs"
            >
              {specLabel(s)}
              {on.has(specKey(s)) && <span className="ml-auto text-[10px] text-muted-foreground">on</span>}
            </DropdownMenuItem>
          ))}
          {specs.length > 0 && (
            <>
              <DropdownMenuSeparator />
              <DropdownMenuItem onSelect={() => onChange([])} className="text-xs text-muted-foreground">
                Remove all
              </DropdownMenuItem>
            </>
          )}
        </DropdownMenuContent>
      </DropdownMenu>

      {open &&
        specs.map((s) => (
          <span
            key={specKey(s)}
            className="flex h-6 items-center gap-1 rounded border border-border bg-background/90 pl-1.5 pr-0.5 font-mono text-[10px] text-foreground backdrop-blur"
          >
            <span className="h-2 w-2 rounded-full" style={{ background: colorOf(specs, s) }} />
            {specLabel(s)}
            <button
              type="button"
              aria-label={`Remove ${specLabel(s)}`}
              onClick={() => onChange(specs.filter((o) => specKey(o) !== specKey(s)))}
              className="rounded p-0.5 text-muted-foreground hover:bg-secondary hover:text-foreground"
            >
              <X className="h-3 w-3" />
            </button>
          </span>
        ))}

      {specs.length > 0 && (
        <button
          type="button"
          aria-label={open ? "Fold the indicator list" : "Show the indicator list"}
          onClick={() => setOpen(!open)}
          className="flex h-6 w-6 items-center justify-center rounded border border-border bg-background/90 text-muted-foreground backdrop-blur hover:text-foreground"
        >
          {open ? <ChevronLeft className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
        </button>
      )}
    </div>
  )
}
