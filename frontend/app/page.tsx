import Link from "next/link"
import HeroCandles from "@/components/landing/hero-candles"
import TickerTape from "@/components/landing/ticker-tape"
import HeroPrice from "@/components/landing/hero-price"
import Wordmark from "@/components/wordmark"
import { CONTACT_EMAIL } from "@/lib/contact"

const APP_URL = process.env.NEXT_PUBLIC_APP_URL ?? "/app"

/* Real output from the app, not invented marketing numbers. */
const LEVELS = [
  { kind: "R", price: "65,102.44", strength: "strong", tests: 71 },
  { kind: "S", price: "64,296.89", strength: "strong", tests: 82 },
  { kind: "S", price: "63,040.40", strength: "medium", tests: 18 },
]

const STEPS = [
  {
    k: "Ask",
    title: "Ask in plain English",
    body: "“Where is liquidity sitting on BTC?” No query language, no indicator setup, no chart drawing.",
  },
  {
    k: "Find",
    title: "Levels price has actually tested",
    body: "100 hours of candles, clustered into the prices the market kept returning to. Each level carries how many times it was tested, so strength is measured, not asserted.",
  },
  {
    k: "Mark",
    title: "On the chart, in one click",
    body: "Accept the levels and they are drawn on your chart with their strength encoded in the line itself. Reject them and nothing moves.",
  },
]

export default function Landing() {
  return (
    <div className="vt min-h-screen" style={{ background: "var(--vt-void)", color: "var(--vt-ink)" }}>
      {/* Nav */}
      <header
        className="sticky top-0 z-30 border-b backdrop-blur-md"
        style={{ borderColor: "var(--vt-line)", background: "rgba(6,17,15,0.82)" }}
      >
        <nav className="mx-auto flex h-16 max-w-6xl items-center justify-between px-6">
          <Wordmark />
          <div className="flex items-center gap-6">
            <a
              href="https://api.vibetrading.club/docs"
              className="hidden font-mono text-xs transition-colors hover:text-[color:var(--vt-ink)] sm:block"
              style={{ color: "var(--vt-ink-dim)" }}
            >
              API
            </a>
            <Link
              href={APP_URL}
              className="rounded-full px-4 py-2 font-mono text-xs font-medium transition-transform hover:scale-[1.03] focus-visible:outline-2 focus-visible:outline-offset-2"
              style={{ background: "var(--vt-mint)", color: "var(--vt-void)", outlineColor: "var(--vt-mint)" }}
            >
              Get started
            </Link>
          </div>
        </nav>
      </header>

      {/* Hero */}
      <section className="relative overflow-hidden">
        <div className="pointer-events-none absolute inset-x-0 bottom-0 h-[380px] opacity-40">
          <HeroCandles />
        </div>
        <div
          className="pointer-events-none absolute inset-x-0 bottom-0 h-[380px]"
          style={{ background: "linear-gradient(to top, var(--vt-void) 4%, transparent 70%)" }}
        />

        <div className="relative mx-auto max-w-6xl px-6 pb-28 pt-20 sm:pt-28">
          <HeroPrice />

          <h1
            className="vt-rise font-display mt-8 max-w-3xl text-balance text-5xl font-extrabold leading-[0.95] tracking-[-0.035em] sm:text-7xl"
            style={{ animationDelay: "60ms" }}
          >
            Find the levels
            <br />
            that actually{" "}
            <span style={{ color: "var(--vt-mint)" }}>hold</span>.
          </h1>

          <p
            className="vt-rise mt-7 max-w-xl text-pretty text-base leading-relaxed sm:text-lg"
            style={{ color: "var(--vt-ink-dim)", animationDelay: "140ms" }}
          >
            VibeTrading reads the last 100 hours of candles, clusters the prices the market
            keeps returning to, and marks them on your chart — with the number of times each
            one was tested.
          </p>

          <div className="vt-rise mt-10 flex flex-wrap items-center gap-4" style={{ animationDelay: "220ms" }}>
            <Link
              href={APP_URL}
              className="group inline-flex items-center gap-2 rounded-full px-7 py-3.5 text-sm font-semibold transition-transform hover:scale-[1.03] focus-visible:outline-2 focus-visible:outline-offset-2"
              style={{ background: "var(--vt-mint)", color: "var(--vt-void)", outlineColor: "var(--vt-mint)" }}
            >
              Get started
              <span className="transition-transform group-hover:translate-x-0.5">→</span>
            </Link>
            <span className="font-mono text-xs" style={{ color: "var(--vt-ink-faint)" }}>
              No signup. Nine pairs, live.
            </span>
          </div>
        </div>
      </section>

      <TickerTape />

      {/* What it does */}
      <section className="mx-auto max-w-6xl px-6 py-24">
        <div className="grid gap-14 lg:grid-cols-[1fr_auto]">
          <div className="max-w-2xl">
            <p
              className="font-mono text-[11px] uppercase tracking-[0.2em]"
              style={{ color: "var(--vt-ink-faint)" }}
            >
              How it works
            </p>
            <div className="mt-10 space-y-11">
              {STEPS.map((s) => (
                <div key={s.k} className="grid grid-cols-[64px_1fr] gap-5">
                  <span
                    className="pt-1 font-mono text-[11px] uppercase tracking-[0.16em]"
                    style={{ color: "var(--vt-mint-deep)" }}
                  >
                    {s.k}
                  </span>
                  <div>
                    <h3 className="font-display text-xl font-bold tracking-[-0.01em]">{s.title}</h3>
                    <p className="mt-2 text-sm leading-relaxed" style={{ color: "var(--vt-ink-dim)" }}>
                      {s.body}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* A real result, shown as the product renders it */}
          <div
            className="h-fit w-full rounded-xl border p-5 lg:w-[330px]"
            style={{ borderColor: "var(--vt-line)", background: "var(--vt-surface)" }}
          >
            <div className="flex items-baseline justify-between">
              <span
                className="font-mono text-[11px] uppercase tracking-[0.16em]"
                style={{ color: "var(--vt-ink-faint)" }}
              >
                Liquidity levels
              </span>
              <span className="font-mono text-[11px]" style={{ color: "var(--vt-ink-faint)" }}>
                BTC · 1h
              </span>
            </div>

            <ul className="mt-5 space-y-4">
              {LEVELS.map((l) => (
                <li key={l.price} className="flex items-start gap-3">
                  <svg width="18" height="10" className="mt-1.5 shrink-0" aria-hidden>
                    <line
                      x1="0"
                      y1="5"
                      x2="18"
                      y2="5"
                      stroke={l.kind === "S" ? "var(--vt-mint)" : "var(--vt-ink-dim)"}
                      strokeWidth={l.strength === "strong" ? 2 : 1.5}
                      strokeDasharray={l.strength === "strong" ? undefined : "5 3"}
                    />
                  </svg>
                  <div>
                    <div className="font-mono text-sm">
                      {l.kind} ${l.price}
                    </div>
                    <div className="font-mono text-[11px]" style={{ color: "var(--vt-ink-faint)" }}>
                      {l.strength} · {l.tests} tests
                    </div>
                  </div>
                </li>
              ))}
            </ul>

            <p
              className="mt-6 border-t pt-4 text-[11px] leading-relaxed"
              style={{ borderColor: "var(--vt-line)", color: "var(--vt-ink-faint)" }}
            >
              Support sits below spot, resistance above. A level that price has broken through
              flips sides.
            </p>
          </div>
        </div>
      </section>

      {/* Close */}
      <section className="border-t" style={{ borderColor: "var(--vt-line)" }}>
        <div className="mx-auto max-w-6xl px-6 py-24 text-center">
          <h2 className="font-display text-balance text-4xl font-extrabold tracking-[-0.03em] sm:text-5xl">
            The market is open right now.
          </h2>
          <Link
            href={APP_URL}
            className="group mt-9 inline-flex items-center gap-2 rounded-full px-8 py-4 text-sm font-semibold transition-transform hover:scale-[1.03] focus-visible:outline-2 focus-visible:outline-offset-2"
            style={{ background: "var(--vt-mint)", color: "var(--vt-void)", outlineColor: "var(--vt-mint)" }}
          >
            Get started
            <span className="transition-transform group-hover:translate-x-0.5">→</span>
          </Link>
        </div>
      </section>

      <footer className="border-t" style={{ borderColor: "var(--vt-line)" }}>
        <div className="mx-auto max-w-6xl px-6 py-9">
          <div className="flex flex-col gap-5 sm:flex-row sm:items-start sm:justify-between">
            <div className="flex flex-col gap-2">
              <Wordmark />
              <a
                href={`mailto:${CONTACT_EMAIL}`}
                className="font-mono text-[11px] transition-colors hover:opacity-80"
                style={{ color: "var(--vt-mint)" }}
              >
                {CONTACT_EMAIL}
              </a>
            </div>

            <nav className="flex flex-wrap gap-x-5 gap-y-2">
              {[
                { href: "/legal/risk", label: "Risk disclosure" },
                { href: "/legal/terms", label: "Terms" },
                { href: "/legal/privacy", label: "Privacy" },
              ].map((l) => (
                <Link
                  key={l.href}
                  href={l.href}
                  className="font-mono text-[11px] transition-colors hover:opacity-80"
                  style={{ color: "var(--vt-ink-dim)" }}
                >
                  {l.label}
                </Link>
              ))}
            </nav>
          </div>

          {/* Stated plainly rather than buried: what this is, and what it is not. */}
          <p
            className="mt-7 max-w-3xl text-[11px] leading-relaxed"
            style={{ color: "var(--vt-ink-faint)" }}
          >
            Analysis, not advice. VibeTrading is an independent project, not a
            broker or investment adviser. It computes technical analysis on
            public market data — it places no trades, holds no funds, and never
            asks for exchange API keys. Trading cryptocurrency can lose you
            money, up to everything you put in. Read the{" "}
            <Link
              href="/legal/risk"
              className="underline underline-offset-2"
              style={{ color: "var(--vt-ink-dim)" }}
            >
              risk disclosure
            </Link>
            .
          </p>
        </div>
      </footer>
    </div>
  )
}
