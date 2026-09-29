/*
 * The hero's chart window. Illustrative, and labelled as such on the page: a W
 * forming on a support the market has tested, drawn as static SVG so the hero
 * costs no chart library and no request. The numbers are the same ones the
 * assistant's levels card has always shown.
 */

const UP = "var(--vt-mint)"
const DOWN = "var(--vt-red)"

// [x, wickTop, wickBottom, bodyTop, bodyHeight, direction]
const CANDLES: [number, number, number, number, number, "up" | "down"][] = [
  [30, 45, 175, 60, 75, "down"],
  [75, 110, 195, 130, 50, "down"],
  [120, 165, 192, 172, 15, "up"],
  [165, 115, 178, 125, 42, "up"],
  [210, 120, 190, 138, 46, "down"],
  [255, 168, 190, 174, 13, "up"],
  [300, 105, 178, 115, 52, "up"],
  [345, 75, 135, 85, 38, "up"],
  [390, 65, 115, 74, 24, "down"],
  [435, 40, 88, 46, 32, "up"],
  [480, 28, 70, 32, 24, "up"],
]

export default function HeroChart() {
  return (
    <figure
      className="relative overflow-hidden rounded-xl border"
      style={{ borderColor: "var(--vt-line-strong)", background: "var(--vt-surface)" }}
    >
      <div
        className="flex items-center justify-between border-b px-4 py-2.5 font-mono"
        style={{ borderColor: "var(--vt-line)" }}
      >
        <div className="flex items-center gap-3 text-[12px]">
          <span className="font-semibold">BTC/USDT</span>
          <span className="text-[11px]" style={{ color: "var(--vt-ink-faint)" }}>
            1h candles
          </span>
        </div>
        <span
          className="rounded border px-2 py-0.5 text-[10px] uppercase tracking-[0.08em]"
          style={{ borderColor: "var(--vt-line)", color: "var(--vt-mint)", background: "var(--vt-raised)" }}
        >
          100h window
        </span>
      </div>

      <div className="relative px-3 py-4 sm:px-4" style={{ background: "#040c0a" }}>
        <div className="flex items-center justify-between">
          <LevelTag kind="R" price="65,102.44" tests={71} color={DOWN} />
          <span className="font-mono text-[10px]" style={{ color: "var(--vt-ink-faint)" }}>
            level 01
          </span>
        </div>

        <svg
          viewBox="0 0 540 240"
          className="my-1 block h-auto w-full"
          role="img"
          aria-label="Illustrative chart: a double bottom forming on a support level that price has tested 82 times, below a resistance tested 71 times."
        >
          <line x1="0" x2="540" y1="28" y2="28" stroke={DOWN} strokeOpacity="0.6" strokeDasharray="3 3" />
          <line x1="0" x2="540" y1="184" y2="184" stroke={UP} strokeOpacity="0.85" strokeWidth="1.2" />
          <line x1="0" x2="540" y1="228" y2="228" stroke={UP} strokeOpacity="0.35" strokeDasharray="2 2" />
          {CANDLES.map(([x, wt, wb, bt, bh, dir]) => (
            <g key={x}>
              <line x1={x} x2={x} y1={wt} y2={wb} stroke="#435650" />
              <rect x={x - 4} y={bt} width="8" height={bh} rx="1" fill={dir === "up" ? UP : DOWN} />
            </g>
          ))}
          <path
            d="M 120 184 L 165 125 L 255 184 L 345 85"
            fill="none"
            stroke="#74d9ba"
            strokeOpacity="0.75"
            strokeDasharray="2 3"
          />
          <circle cx="165" cy="125" r="3" fill="#ffd4a3" />
          <circle cx="345" cy="85" r="3.5" fill={UP} />
        </svg>

        <div className="flex items-center justify-between">
          <LevelTag kind="S" price="64,296.89" tests={82} color={UP} />
          <span className="font-mono text-[10px]" style={{ color: "var(--vt-ink-faint)" }}>
            level 02
          </span>
        </div>
      </div>

      <figcaption
        className="flex items-center justify-between gap-3 border-t px-4 py-2 font-mono text-[11px]"
        style={{ borderColor: "var(--vt-line)", color: "var(--vt-ink-dim)" }}
      >
        <span className="flex items-center gap-1.5">
          <span className="h-1.5 w-1.5 rounded-full" style={{ background: "var(--vt-mint-deep)" }} />
          Illustrative: a W forming on a tested support
        </span>
      </figcaption>
    </figure>
  )
}

function LevelTag({ kind, price, tests, color }: { kind: string; price: string; tests: number; color: string }) {
  return (
    <span
      className="inline-flex items-center gap-2 rounded border px-2.5 py-1 font-mono"
      style={{ borderColor: `color-mix(in srgb, ${color} 30%, transparent)`, background: "var(--vt-surface)" }}
    >
      <span className="text-[10px] font-bold" style={{ color }}>
        {kind}
      </span>
      <span className="text-[11px] font-semibold">${price}</span>
      <span style={{ color: "var(--vt-ink-faint)" }}>·</span>
      <span className="text-[10px] uppercase tracking-wider" style={{ color }}>
        {tests} tests
      </span>
    </span>
  )
}
