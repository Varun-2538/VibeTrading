import type { Metadata } from "next"
import DocShell from "@/components/doc-shell"

export const metadata: Metadata = {
  title: "Architecture — VibeTrading",
  description:
    "How VibeTrading is built: Next.js on Vercel, FastAPI and TimescaleDB on Google Compute Engine, and a deterministic analysis layer that uses no machine learning.",
}

/* Palette matched to the site so the diagram reads as part of the page. */
const MINT = "#7af0ce"
const DIM = "#7e9a92"
const FAINT = "#47605a"
const SURFACE = "#0b1a17"
const LINE = "rgba(122,240,206,0.28)"

function Box({
  x,
  y,
  w,
  h,
  title,
  sub,
  accent = false,
}: {
  x: number
  y: number
  w: number
  h: number
  title: string
  sub?: string
  accent?: boolean
}) {
  return (
    <g>
      <rect
        x={x}
        y={y}
        width={w}
        height={h}
        rx="5"
        fill={SURFACE}
        stroke={accent ? MINT : LINE}
        strokeWidth="1"
      />
      <text
        x={x + 12}
        y={y + (sub ? 21 : h / 2 + 4)}
        fill={accent ? MINT : "#e6f4ef"}
        fontSize="12"
        fontFamily="ui-monospace, monospace"
      >
        {title}
      </text>
      {sub && (
        <text
          x={x + 12}
          y={y + 38}
          fill={FAINT}
          fontSize="10.5"
          fontFamily="ui-monospace, monospace"
        >
          {sub}
        </text>
      )}
    </g>
  )
}

function Arrow({
  x1,
  y1,
  x2,
  y2,
  label,
  dashed = false,
}: {
  x1: number
  y1: number
  x2: number
  y2: number
  label?: string
  dashed?: boolean
}) {
  return (
    <g>
      <line
        x1={x1}
        y1={y1}
        x2={x2}
        y2={y2}
        stroke={DIM}
        strokeWidth="1"
        strokeDasharray={dashed ? "4 3" : undefined}
        markerEnd="url(#arrowhead)"
      />
      {label && (
        <text
          x={(x1 + x2) / 2}
          y={y1 === y2 ? y1 - 7 : (y1 + y2) / 2 - 5}
          fill={FAINT}
          fontSize="9.5"
          textAnchor="middle"
          fontFamily="ui-monospace, monospace"
        >
          {label}
        </text>
      )}
    </g>
  )
}

function Diagram() {
  return (
    <figure className="my-8">
      <div className="overflow-x-auto">
        <svg
          viewBox="0 0 760 430"
          className="w-full min-w-[680px]"
          role="img"
          aria-label="Request flow: the browser talks to Next.js on Vercel and to the API behind Caddy on Google Compute Engine, which reads TimescaleDB and Redis; live prices stream from the exchange directly to the browser."
        >
          <defs>
            <marker
              id="arrowhead"
              markerWidth="7"
              markerHeight="7"
              refX="6"
              refY="2.5"
              orient="auto"
            >
              <path d="M0,0 L6,2.5 L0,5" fill="none" stroke={DIM} strokeWidth="1" />
            </marker>
          </defs>

          <Box x={20} y={20} w={190} h={52} title="Browser" sub="charts, overlays" accent />

          {/* Vercel */}
          <rect
            x={20}
            y={110}
            width={190}
            height={90}
            rx="6"
            fill="none"
            stroke={LINE}
            strokeDasharray="3 3"
          />
          <text x={30} y={128} fill={FAINT} fontSize="9.5" fontFamily="ui-monospace, monospace">
            VERCEL
          </text>
          <Box x={32} y={138} w={166} h={48} title="Next.js 15" sub="App Router, SSG" />

          {/* GCP */}
          <rect
            x={300}
            y={95}
            width={440}
            height={300}
            rx="6"
            fill="none"
            stroke={LINE}
            strokeDasharray="3 3"
          />
          <text x={312} y={114} fill={MINT} fontSize="9.5" fontFamily="ui-monospace, monospace">
            GOOGLE COMPUTE ENGINE · e2-medium · asia-south1-a
          </text>

          <Box x={315} y={128} w={180} h={48} title="Caddy 2" sub="automatic TLS" />
          <Box x={315} y={200} w={180} h={52} title="FastAPI" sub="Python 3.11" accent />
          <Box x={315} y={276} w={180} h={48} title="analysis/" sub="pure Python, no ML" />
          <Box x={315} y={336} w={180} h={44} title="agents/" sub="Cerebras — chat only" />

          <Box x={540} y={200} w={180} h={52} title="TimescaleDB" sub="candles, annotations" />
          <Box x={540} y={276} w={180} h={48} title="Redis 7" sub="hot-path cache" />

          {/* Exchange */}
          <Box x={540} y={20} w={180} h={52} title="Binance" sub="public REST + WS" />

          {/* Flows */}
          <Arrow x1={115} y1={72} x2={115} y2={136} label="HTML/JS" />
          {/* Separated vertically: the REST call out and the tick stream back
              sit on the same edge and collided when drawn at one height. */}
          <Arrow x1={210} y1={60} x2={313} y2={60} label="REST" />
          <Arrow x1={405} y1={60} x2={405} y2={126} />
          <Arrow x1={405} y1={176} x2={405} y2={198} />
          <Arrow x1={405} y1={252} x2={405} y2={274} />
          <Arrow x1={405} y1={324} x2={405} y2={334} />
          <Arrow x1={495} y1={226} x2={538} y2={226} />
          <Arrow x1={495} y1={244} x2={538} y2={294} />
          <Arrow x1={630} y1={72} x2={630} y2={198} label="candles" />
          <Arrow x1={540} y1={32} x2={212} y2={32} label="live ticks (WebSocket)" dashed />
        </svg>
      </div>
      <figcaption className="mt-2 text-[11px]" style={{ color: FAINT }}>
        Live prices stream from the exchange straight to the browser (dashed);
        everything historical and analytical goes through the API.
      </figcaption>
    </figure>
  )
}

export default function ArchitecturePage() {
  return (
    <DocShell wide>
      <h1>Architecture</h1>
      <p className="lede">
        A small, boring, legible stack. One virtual machine, three containers, a
        static frontend, and an analysis layer with no machine learning in it.
      </p>

      <Diagram />

      <h2>What runs where</h2>
      <p>
        The frontend is a Next.js 15 App Router project on Vercel — mostly static,
        with the chart rendered client-side by Lightweight Charts and pattern
        geometry drawn in an SVG layer positioned through the chart's own
        coordinate functions.
      </p>
      <p>
        Everything else runs in Docker Compose on a single Google Compute Engine{" "}
        <code>e2-medium</code> in <code>asia-south1-a</code>: Caddy terminating
        TLS, a FastAPI service, TimescaleDB, and Redis. One machine is genuinely
        enough at this stage, and pretending otherwise would mean paying for
        idle capacity.
      </p>

      <h2>Why TimescaleDB</h2>
      <p>
        Candles are time-series data and the access pattern is always "this
        symbol, this timeframe, this window". TimescaleDB gives us PostgreSQL —
        ordinary SQL, ordinary tooling — with hypertables that partition on time
        underneath. Redis sits in front for the hot path, since the same recent
        window is requested repeatedly as users pan around a chart.
      </p>

      <h2>The analysis layer has no model in it</h2>
      <p>
        This is the part people assume is machine learning, and it is not. Level
        clustering and W/M detection are deterministic Python: find swing pivots,
        compare them against thresholds expressed in ATR, score the geometry.
        Given the same candles it returns the same answer, and every number it
        produces can be traced to a rule.
      </p>
      <p>
        Thresholds are in ATR rather than percentages for a reason we learned by
        getting it wrong. A fixed percentage is calibrated for one timeframe and
        collapses on the others — the shoulder tolerance used by widely-copied
        Pine scripts works out to 0.9 ATR on a daily chart but around{" "}
        <strong>65 ATR on a 1-minute chart</strong>, where it treats any two lows
        as a match. ATR-relative thresholds behave identically across timeframes.
      </p>
      <p>
        The language model is used only for the conversational interface. It
        never computes a level or a pattern, so a bad generation cannot corrupt
        the analysis — the worst it can do is describe it clumsily.
      </p>

      <h2>Analysis follows the viewport</h2>
      <p>
        Every analysis endpoint takes the same window —{" "}
        <code>{"{symbol, timeframe, from, to}"}</code> — so the chart can ask
        about exactly the candles it is displaying. Pan or zoom and the request
        is re-issued for the new range, debounced, with the previous request
        aborted. What you are looking at is what gets analysed, rather than a
        fixed lookback that happens not to match the screen.
      </p>

      <h2>Scale, and why it is its own control</h2>
      <p>
        A single pivot window cannot see both kinds of pattern traders care
        about. A wide window finds clean multi-day swings and is structurally
        blind to the tight double bottoms that form inside a range — the second
        low of one is simply not the lowest bar for four bars either side. So the
        detector searches several widths and merges the results, with a guard
        that stops a large pattern from swallowing a small one nested inside it.
      </p>
      <p>
        Scale and strictness are deliberately separate axes. Bundled together,
        "look for smaller structures" and "accept worse examples" could only be
        asked for at once, which made the one combination a scalper actually
        wants — small but precise — impossible to express.
      </p>

      <h2>Testing</h2>
      <p>
        77 tests. Pattern fixtures are built from line segments so the geometry
        is known exactly and assertions can be made on prices rather than on
        "something was found". A good number of those tests exist because a real
        chart disagreed with the detector and the disagreement turned out to be
        our bug — each one carries a docstring explaining what broke.
      </p>

      <h2>What we would change with more traffic</h2>
      <p>
        Honestly, not much yet — a single <code>e2-medium</code> serves the
        current load with sub-250ms analysis responses. The first things to move
        would be read replicas for TimescaleDB and pushing candle fetching onto a
        scheduled worker rather than doing it inline on cache misses. We would
        rather add that when it is needed than build it speculatively.
      </p>
    </DocShell>
  )
}
