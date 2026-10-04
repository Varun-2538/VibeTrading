import Image from "next/image"
import Link from "next/link"
import { ArrowRight, ArrowUpRight, CheckCircle2, GitBranch, KeyRound, Network, ShieldCheck, Wallet } from "lucide-react"
import HeroChart from "@/components/landing/hero-chart"
import TickerTape from "@/components/landing/ticker-tape"
import HeroPrice from "@/components/landing/hero-price"
import Wordmark from "@/components/wordmark"
import { CONTACT_EMAIL } from "@/lib/contact"
import { COMPANY, FOUNDERS, FOUNDERS_SENTENCE, ROADMAP } from "@/lib/company"

const APP_URL = process.env.NEXT_PUBLIC_APP_URL ?? "/app"
const API_DOCS_URL = "https://api.vibetrading.club/docs"
const CONTRACTS_URL = `${COMPANY.socials.github}/tree/main/contracts`

/*
 * What is live, one sentence each. Everything here is on the deployed panel
 * today; anything still being built belongs in ROADMAP, not this list.
 */
const FEATURES = [
  {
    title: "Liquidity levels",
    body: "The prices the market keeps returning to, each carrying how many times it was tested. Strength is measured, not asserted.",
  },
  {
    title: "W and M patterns",
    body: "Double bottoms and tops tracked through their life — forming, approaching the neckline, confirmed by a close beyond it — so a setup is visible while it is still a setup.",
  },
  {
    title: "Strategy alerts",
    body: "Set a condition on a pattern or a level. It runs on the server and fires with the browser closed, and it can be backtested on data the tuning never saw before you trust it.",
  },
  {
    title: "Plain-English assistant",
    body: "Ask where liquidity is sitting and get an answer you can mark on the chart. The model handles the conversation; it never computes a level.",
  },
  {
    title: "Wallet sign-in",
    body: "Rules belong to a wallet address, proven by signature. No email, no password, nothing for us to store or lose.",
  },
  {
    title: "Public API",
    body: "Every level and pattern the panel draws is available over a documented API, so the analysis can live inside your own tools.",
    href: API_DOCS_URL,
  },
]

/*
 * The vault, stated in the contract's own function names (contracts/README.md).
 * Nothing here is a claim the contract does not enforce, and the page says
 * "in testing" because it is: vault execution is off until the testnet run and
 * an audit.
 */
const CAN = [
  {
    fn: "openPosition()",
    tag: "Capped",
    body: "Sized and slippage-limited by the caps you set on your own vault. It writes the stop, target and deadline once.",
  },
  {
    fn: "closeByOperator()",
    tag: "Exit only",
    body: "Closes a position on an opposing signal or a kill switch. It can only turn the asset back into USDC.",
  },
  {
    fn: "closeIfStopped()",
    tag: "Anyone",
    body: "Permissionless. Reverts unless the Chainlink price is at the stop, so a stranger can enforce your exit if we are down.",
  },
]

const CANNOT = [
  {
    fn: "withdraw()",
    tag: "Owner only",
    body: "There is no operator path that moves funds out. Only your wallet can withdraw, any time, position open or not.",
  },
  {
    fn: "moveTheStop()",
    tag: "Does not exist",
    body: "The stop is written at open. No function changes it afterwards, not for us and not for you.",
  },
  {
    fn: "raiseTheCap()",
    tag: "In the contract",
    body: "A $500 total cap per vault is hardcoded in the contract, so we cannot raise it either.",
  },
]

const STEPS = [
  {
    n: "01",
    title: "Ask in plain English",
    body: "“Where is liquidity sitting on BTC?” No query language, no indicator setup, no chart drawing.",
    foot: "Assistant",
  },
  {
    n: "02",
    title: "Levels price has tested",
    body: "100 hours of candles, clustered into the prices the market kept returning to, each with its test count.",
    foot: "Deterministic clustering",
  },
  {
    n: "03",
    title: "Backtest before it acts",
    body: "A rule cannot be armed to trade until a backtest on unseen data clears the threshold you set.",
    foot: "Mandatory gate",
  },
  {
    n: "04",
    title: "Arm it in your vault",
    body: "You sign once to grant the operator a limited, expiring role in a contract you own and can revoke.",
    foot: "You hold custody",
  },
]

const PILLARS = [
  {
    icon: Network,
    title: "One vault per user",
    body: "No pooled liquidity. Your balance never shares contract state or counterparty risk with anyone else's.",
  },
  {
    icon: KeyRound,
    title: "Revoke in one transaction",
    body: "Remove the operator on-chain whenever you like. Withdrawing needs only your wallet, not our front end.",
  },
  {
    icon: GitBranch,
    title: "Chainlink-authorised exits",
    body: "The feed decides whether a stop or target exit is allowed; a minimum-out derived from it limits what a caller can skim.",
  },
  {
    icon: ShieldCheck,
    title: "Small by design",
    body: "A hardcoded $500 cap per vault while the contract is unaudited. It is unaudited, and the risk page says so.",
  },
]

const eyebrow = "font-mono text-[11px] uppercase tracking-[0.2em]"

export default function Landing() {
  return (
    <div className="vt min-h-screen" style={{ background: "var(--vt-void)", color: "var(--vt-ink)" }}>
      {/* Nav */}
      <header
        className="sticky top-0 z-30 border-b backdrop-blur-md"
        style={{ borderColor: "var(--vt-line)", background: "rgba(6,17,15,0.82)" }}
      >
        <nav className="mx-auto flex h-16 max-w-[1360px] items-center justify-between gap-4 px-6 lg:px-12">
          <div className="flex items-center gap-4">
            <Wordmark />
            <span
              className="hidden rounded border px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.08em] sm:inline"
              style={{ borderColor: "var(--vt-line)", background: "var(--vt-surface)", color: "var(--vt-mint)" }}
            >
              {COMPANY.stage}
            </span>
          </div>
          <div className="flex items-center gap-5 lg:gap-7">
            {[
              { href: "#vault", label: "Vault" },
              { href: "#product", label: "Product" },
              { href: "#about", label: "About" },
              { href: API_DOCS_URL, label: "API" },
            ].map((l) => (
              <a
                key={l.href}
                href={l.href}
                className="hidden font-mono text-xs transition-colors hover:text-[color:var(--vt-ink)] md:block"
                style={{ color: "var(--vt-ink-dim)" }}
              >
                {l.label}
              </a>
            ))}
            <Link
              href={APP_URL}
              className="inline-flex items-center gap-1.5 rounded-md px-3.5 py-2 font-mono text-xs font-semibold transition-transform hover:scale-[1.03] focus-visible:outline-2 focus-visible:outline-offset-2"
              style={{ background: "var(--vt-mint)", color: "var(--vt-void)", outlineColor: "var(--vt-mint)" }}
            >
              <Wallet size={14} aria-hidden />
              Launch app
            </Link>
          </div>
        </nav>
      </header>

      {/* Hero */}
      <section className="relative overflow-hidden">
        <div
          className="pointer-events-none absolute -top-40 left-1/2 h-[480px] w-[780px] -translate-x-1/2 rounded-full blur-[140px]"
          style={{ background: "rgba(122,240,206,0.04)" }}
        />
        <div className="relative mx-auto grid max-w-[1360px] items-center gap-12 px-6 pb-20 pt-16 sm:pt-20 lg:grid-cols-12 lg:gap-14 lg:px-12 lg:pb-24">
          <div className="flex flex-col lg:col-span-6">
            <HeroPrice />

            <h1
              className="vt-rise font-display mt-8 text-balance text-5xl font-extrabold leading-[1] tracking-[-0.035em] sm:text-6xl lg:text-[64px]"
              style={{ animationDelay: "60ms" }}
            >
              Find the levels that actually{" "}
              <span style={{ color: "var(--vt-mint)" }}>hold</span>.
            </h1>

            <p
              className="vt-rise mt-6 max-w-xl text-pretty text-base leading-relaxed sm:text-lg"
              style={{ color: "var(--vt-ink-dim)", animationDelay: "140ms" }}
            >
              VibeTrading reads the last 100 hours of candles, clusters the prices the market keeps
              returning to, and marks them on your chart — with the number of times each one was
              tested. When you are ready, a rule can trade them from a vault you own.
            </p>

            <div className="vt-rise mt-9 flex flex-wrap items-center gap-x-5 gap-y-3" style={{ animationDelay: "220ms" }}>
              <Link
                href={APP_URL}
                className="group inline-flex items-center gap-2 rounded-lg px-6 py-3.5 text-sm font-semibold transition-transform hover:scale-[1.03] focus-visible:outline-2 focus-visible:outline-offset-2"
                style={{ background: "var(--vt-mint)", color: "var(--vt-void)", outlineColor: "var(--vt-mint)" }}
              >
                Get started
                <ArrowRight size={16} aria-hidden className="transition-transform group-hover:translate-x-0.5" />
              </Link>
              <a
                href={CONTRACTS_URL}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 font-mono text-[13px] transition-colors hover:text-[color:var(--vt-mint)]"
                style={{ color: "var(--vt-ink-dim)" }}
              >
                Read the contract <ArrowUpRight size={14} aria-hidden />
              </a>
              <a
                href={API_DOCS_URL}
                className="font-mono text-[13px] transition-colors hover:text-[color:var(--vt-mint)]"
                style={{ color: "var(--vt-ink-dim)" }}
              >
                API docs
              </a>
            </div>

            <ul
              className="mt-8 flex flex-wrap items-center gap-x-5 gap-y-2 font-mono text-[11px]"
              style={{ color: "var(--vt-ink-faint)" }}
            >
              {["No signup", "Nine pairs, live", "Non-custodial"].map((t) => (
                <li key={t} className="flex items-center gap-1.5">
                  <CheckCircle2 size={14} aria-hidden style={{ color: "var(--vt-mint-deep)" }} />
                  {t}
                </li>
              ))}
            </ul>
          </div>

          <div className="lg:col-span-6">
            <HeroChart />
          </div>
        </div>
      </section>

      <TickerTape />

      {/* What the vault can and cannot do */}
      <section
        id="vault"
        className="scroll-mt-16 border-b"
        style={{ borderColor: "var(--vt-line)", background: "rgba(3,8,7,0.55)" }}
      >
        <div className="mx-auto max-w-[1360px] px-6 py-24 lg:px-12">
          <div className="flex flex-col gap-6 md:flex-row md:items-end md:justify-between">
            <div>
              <p className={eyebrow} style={{ color: "var(--vt-mint-deep)" }}>
                The vault contract
              </p>
              <h2 className="font-display mt-4 text-balance text-3xl font-extrabold tracking-[-0.03em] sm:text-4xl">
                What the bot can and cannot do.
              </h2>
            </div>
            <p className="max-w-md text-sm leading-relaxed" style={{ color: "var(--vt-ink-dim)" }}>
              We run the bot, so we hold an operator key. The contract is written so that key is
              survivable: it can open and close a position, and there is no path to your money.
            </p>
          </div>

          <div className="mt-14 grid gap-6 md:grid-cols-2 md:gap-8">
            <VaultCard tone="var(--vt-mint)" title="The operator can" role="operator role" items={CAN} />
            <VaultCard
              tone="var(--vt-red)"
              title="The operator cannot"
              role="no such function"
              items={CANNOT}
              struck
            />
          </div>

          <p className="mt-6 font-mono text-[11px] leading-relaxed" style={{ color: "var(--vt-ink-faint)" }}>
            Vault execution is switched off while the contract goes to a testnet and an audit. It
            is unaudited today.
          </p>
        </div>
      </section>

      {/* How it works */}
      <section className="mx-auto max-w-[1360px] px-6 py-24 lg:px-12">
        <div className="max-w-xl">
          <p className={eyebrow} style={{ color: "var(--vt-mint-deep)" }}>
            How it works
          </p>
          <h2 className="font-display mt-4 text-3xl font-extrabold tracking-[-0.03em] sm:text-4xl">
            From a question to a guarded trade.
          </h2>
          <p className="mt-3 text-sm leading-relaxed" style={{ color: "var(--vt-ink-dim)" }}>
            No PineScript, no cluttered indicators. Each step is something you can inspect.
          </p>
        </div>

        <ol className="mt-12 grid gap-5 sm:grid-cols-2 lg:grid-cols-4 lg:gap-6">
          {STEPS.map((s) => (
            <li
              key={s.n}
              className="flex min-h-[220px] flex-col justify-between rounded-xl border p-6 transition-colors hover:border-[color:var(--vt-line-strong)]"
              style={{ borderColor: "var(--vt-line)", background: "var(--vt-surface)" }}
            >
              <div>
                <span className="font-mono text-xl font-bold" style={{ color: "var(--vt-mint)" }}>
                  {s.n}
                </span>
                <h3 className="font-display mt-4 text-base font-bold tracking-[-0.01em]">{s.title}</h3>
                <p className="mt-2 text-sm leading-relaxed" style={{ color: "var(--vt-ink-dim)" }}>
                  {s.body}
                </p>
              </div>
              <div
                className="mt-6 border-t pt-4 font-mono text-[10px] uppercase tracking-[0.1em]"
                style={{ borderColor: "var(--vt-line)", color: "var(--vt-ink-faint)" }}
              >
                {s.foot}
              </div>
            </li>
          ))}
        </ol>
      </section>

      {/*
        Product. Shown as it renders, not described: two real screenshots of the
        deployed panel, then one line per feature that is live today. The stage
        is stated up front so nobody has to guess what "beta" means here.
      */}
      <section
        id="product"
        className="scroll-mt-16 border-t"
        style={{ borderColor: "var(--vt-line)" }}
      >
        <div className="mx-auto max-w-[1360px] px-6 py-24 lg:px-12">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <p className={eyebrow} style={{ color: "var(--vt-mint-deep)" }}>
                The product
              </p>
              <h2 className="font-display mt-4 max-w-2xl text-balance text-3xl font-extrabold tracking-[-0.03em] sm:text-4xl">
                Live today, in public beta.
              </h2>
            </div>
            <dl
              className="flex flex-wrap gap-x-6 gap-y-1 font-mono text-[11px]"
              style={{ color: "var(--vt-ink-dim)" }}
            >
              {[
                ["Stage", COMPANY.stage],
                ["Pairs", "Nine, live from Binance"],
                ["Access", "No signup"],
              ].map(([k, v]) => (
                <div key={k} className="flex gap-2">
                  <dt style={{ color: "var(--vt-ink-faint)" }}>{k}</dt>
                  <dd>{v}</dd>
                </div>
              ))}
            </dl>
          </div>

          {/* The desktop panel with levels and patterns drawn, and the phone
              layout beside it. Both are captures of the deployed app. */}
          <div className="mt-12 grid items-start gap-5 lg:grid-cols-[1fr_260px]">
            <figure
              className="overflow-hidden rounded-xl border"
              style={{ borderColor: "var(--vt-line-strong)", background: "var(--vt-surface)" }}
            >
              <Image
                src="/product/panel-desktop.png"
                width={1440}
                height={900}
                alt="The VibeTrading panel on desktop: Robinhood Chain's ETH/USDG and stock tokens in the watchlist, a SOL 15m chart with RSI and MACD, and the assistant marking the double tops it found in red - each labelled completed, with the neckline and the target it hit."
                className="block h-auto w-full"
                priority={false}
              />
              <figcaption
                className="border-t px-4 py-2.5 font-mono text-[11px]"
                style={{ borderColor: "var(--vt-line)", color: "var(--vt-ink-faint)" }}
              >
                Desktop · SOL 15m · the assistant marks completed W/M patterns
              </figcaption>
            </figure>
            <figure
              className="mx-auto w-full max-w-[260px] overflow-hidden rounded-xl border"
              style={{ borderColor: "var(--vt-line-strong)", background: "var(--vt-surface)" }}
            >
              <Image
                src="/product/panel-phone.png"
                width={390}
                height={844}
                alt="The same panel on a phone: the chart with RSI and MACD fills the screen, the timeframes sit under the symbol, and a bottom bar switches between chart, analysis and assistant."
                className="block h-auto w-full"
              />
              <figcaption
                className="border-t px-4 py-2.5 font-mono text-[11px]"
                style={{ borderColor: "var(--vt-line)", color: "var(--vt-ink-faint)" }}
              >
                Phone · same data
              </figcaption>
            </figure>
          </div>

          <ul className="mt-14 grid gap-x-10 gap-y-9 sm:grid-cols-2 lg:grid-cols-3">
            {FEATURES.map((f) => (
              <li key={f.title}>
                <h3 className="font-display text-lg font-bold tracking-[-0.01em]">{f.title}</h3>
                <p className="mt-2 text-sm leading-relaxed" style={{ color: "var(--vt-ink-dim)" }}>
                  {f.body}
                </p>
                {f.href && (
                  <a
                    href={f.href}
                    className="mt-2 inline-block font-mono text-[11px] underline underline-offset-4 transition-opacity hover:opacity-80"
                    style={{ color: "var(--vt-mint)" }}
                  >
                    api.vibetrading.club/docs
                  </a>
                )}
              </li>
            ))}
          </ul>
        </div>
      </section>

      {/* Guarantees */}
      <section className="border-t" style={{ borderColor: "var(--vt-line)", background: "rgba(3,8,7,0.4)" }}>
        <div className="mx-auto max-w-[1360px] px-6 py-24 lg:px-12">
          <div className="flex flex-col gap-6 md:flex-row md:items-end md:justify-between">
            <div>
              <p className={eyebrow} style={{ color: "var(--vt-mint-deep)" }}>
                Security
              </p>
              <h2 className="font-display mt-4 text-balance text-3xl font-extrabold tracking-[-0.03em] sm:text-4xl">
                Built to measure, not to assert.
              </h2>
            </div>
            <p className="max-w-md text-sm leading-relaxed" style={{ color: "var(--vt-ink-dim)" }}>
              Designed without custody, pooled balances or an upgrade path for us to reach into your
              vault.
            </p>
          </div>

          <ul className="mt-12 grid gap-5 sm:grid-cols-2 lg:grid-cols-4 lg:gap-6">
            {PILLARS.map(({ icon: Icon, title, body }) => (
              <li
                key={title}
                className="flex flex-col gap-3 rounded-xl border p-6"
                style={{ borderColor: "var(--vt-line)", background: "var(--vt-surface)" }}
              >
                <Icon size={22} aria-hidden style={{ color: "var(--vt-mint)" }} />
                <h3 className="font-display text-base font-bold tracking-[-0.01em]">{title}</h3>
                <p className="text-sm leading-relaxed" style={{ color: "var(--vt-ink-dim)" }}>
                  {body}
                </p>
              </li>
            ))}
          </ul>
        </div>
      </section>

      {/*
        About. Who is building this, why, and what comes next. Written as
        intent rather than promises: the roadmap lists what is in the repo, not
        what would sound good.
      */}
      <section
        id="about"
        className="scroll-mt-16 border-t"
        style={{ borderColor: "var(--vt-line)" }}
      >
        <div className="mx-auto max-w-[1360px] px-6 py-24 lg:px-12">
          <div className="grid gap-14 lg:grid-cols-[1fr_360px]">
            <div className="max-w-2xl">
              <p className={eyebrow} style={{ color: "var(--vt-mint-deep)" }}>
                About
              </p>
              <h2 className="font-display mt-4 text-balance text-3xl font-extrabold tracking-[-0.03em] sm:text-4xl">
                Why this exists.
              </h2>
              <div
                className="mt-6 space-y-4 text-base leading-relaxed"
                style={{ color: "var(--vt-ink-dim)" }}
              >
                <p>
                  Most charting tools hand you an opinion drawn as a line. {COMPANY.name} was
                  started to replace that with a count: how many times price actually came back
                  to a level, how far a pattern is through its life, all expressed in the chart's
                  own units so the answer holds on a one-minute chart and a daily chart alike.
                </p>
                <p>
                  The analysis is deterministic and every score can be explained. The plan is to
                  grow it from something you read into something that watches the market for you
                  and acts when a condition is met — starting with alerts, and building outward
                  from there.
                </p>
              </div>

              <dl
                className="mt-8 flex flex-wrap gap-x-6 gap-y-2 font-mono text-[11px]"
                style={{ color: "var(--vt-ink-dim)" }}
              >
                {[
                  ["Founded", COMPANY.founded],
                  ["Status", COMPANY.status],
                  ["Stage", COMPANY.stage],
                ].map(([k, v]) => (
                  <div key={k} className="flex gap-2">
                    <dt style={{ color: "var(--vt-ink-faint)" }}>{k}</dt>
                    <dd>{v}</dd>
                  </div>
                ))}
              </dl>

              {/* Founders */}
              <div className="mt-12">
                <p className={eyebrow} style={{ color: "var(--vt-ink-faint)" }}>
                  {FOUNDERS.length > 1 ? "Founders" : "Founder"}
                </p>
                <ul className="mt-5 grid gap-4 sm:grid-cols-2">
                  {FOUNDERS.map((f) => (
                    <li
                      key={f.name}
                      className="rounded-xl border p-5"
                      style={{ borderColor: "var(--vt-line)", background: "var(--vt-surface)" }}
                    >
                      <div className="font-display text-lg font-bold tracking-[-0.01em]">
                        {f.name}
                      </div>
                      <div className="mt-0.5 text-sm" style={{ color: "var(--vt-ink-dim)" }}>
                        {f.title}, {COMPANY.name}
                      </div>
                      <a
                        href={f.linkedin}
                        target="_blank"
                        rel="noopener noreferrer me"
                        className="mt-4 inline-block font-mono text-[11px] underline underline-offset-4 transition-opacity hover:opacity-80"
                        style={{ color: "var(--vt-mint)" }}
                      >
                        LinkedIn profile
                      </a>
                    </li>
                  ))}
                </ul>
              </div>
            </div>

            {/* Roadmap. The labels really are a sequence. */}
            <div>
              <p className={eyebrow} style={{ color: "var(--vt-ink-faint)" }}>
                Roadmap
              </p>
              <ol className="mt-8 space-y-8">
                {ROADMAP.map((r) => (
                  <li key={r.title} className="grid grid-cols-[84px_1fr] gap-4">
                    <span
                      className="pt-0.5 font-mono text-[11px] uppercase tracking-[0.14em]"
                      style={{ color: r.when === "Live" ? "var(--vt-mint)" : "var(--vt-mint-deep)" }}
                    >
                      {r.when}
                    </span>
                    <div>
                      <h3 className="text-sm font-semibold">{r.title}</h3>
                      <p className="mt-1.5 text-sm leading-relaxed" style={{ color: "var(--vt-ink-dim)" }}>
                        {r.body}
                      </p>
                    </div>
                  </li>
                ))}
              </ol>
            </div>
          </div>
        </div>
      </section>

      {/* Close */}
      <section className="border-t" style={{ borderColor: "var(--vt-line)" }}>
        <div className="mx-auto flex max-w-2xl flex-col items-center gap-6 px-6 py-24 text-center">
          <span
            className="inline-flex items-center gap-2 rounded-full border px-3 py-1 font-mono text-[10px] uppercase tracking-[0.1em]"
            style={{ borderColor: "var(--vt-line)", background: "var(--vt-surface)", color: "var(--vt-mint)" }}
          >
            <span className="h-1.5 w-1.5 animate-pulse rounded-full" style={{ background: "var(--vt-mint)" }} />
            Public beta · vaults in testing
          </span>
          <h2 className="font-display text-balance text-4xl font-extrabold tracking-[-0.03em] sm:text-5xl">
            The market is open right now.
          </h2>
          <p className="max-w-lg text-[15px] leading-relaxed" style={{ color: "var(--vt-ink-dim)" }}>
            Read the levels and patterns today, with no registration. Set rules that alert you, and
            backtest them before you trust them.
          </p>
          <div className="flex flex-wrap items-center justify-center gap-4 pt-1">
            <Link
              href={APP_URL}
              className="group inline-flex items-center gap-2 rounded-lg px-7 py-3.5 text-sm font-semibold transition-transform hover:scale-[1.03] focus-visible:outline-2 focus-visible:outline-offset-2"
              style={{ background: "var(--vt-mint)", color: "var(--vt-void)", outlineColor: "var(--vt-mint)" }}
            >
              Launch app
              <ArrowRight size={16} aria-hidden className="transition-transform group-hover:translate-x-0.5" />
            </Link>
            <a
              href={API_DOCS_URL}
              className="font-mono text-[13px] transition-colors hover:text-[color:var(--vt-mint)]"
              style={{ color: "var(--vt-ink-dim)" }}
            >
              Explore the API
            </a>
          </div>
        </div>
      </section>

      <footer className="border-t" style={{ borderColor: "var(--vt-line)" }}>
        <div className="mx-auto max-w-[1360px] px-6 py-9 lg:px-12">
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
                { href: "#about", label: "About" },
                { href: "/architecture", label: "Architecture" },
                { href: CONTRACTS_URL, label: "Contracts" },
                { href: COMPANY.socials.x, label: "X" },
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
            Analysis, not advice. VibeTrading is an early-stage company founded by{" "}
            {FOUNDERS_SENTENCE}, not a broker or investment adviser. It computes technical analysis on
            public market data, and can trade it inside a contract you own if
            you switch that on — it holds no funds, cannot withdraw from that
            contract, and never
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

type VaultItem = { fn: string; tag: string; body: string }

function VaultCard({
  tone,
  title,
  role,
  items,
  struck = false,
}: {
  tone: string
  title: string
  role: string
  items: VaultItem[]
  struck?: boolean
}) {
  const edge = `color-mix(in srgb, ${tone} 22%, transparent)`
  return (
    <div className="rounded-xl border p-6 sm:p-8" style={{ borderColor: edge, background: "var(--vt-surface)" }}>
      <div
        className="flex items-center justify-between gap-3 border-b pb-5"
        style={{ borderColor: "var(--vt-line)" }}
      >
        <div className="flex items-center gap-2.5">
          <span className="h-2 w-2 rounded-full" style={{ background: tone }} />
          <h3 className="font-mono text-[13px] font-bold uppercase tracking-wide" style={{ color: tone }}>
            {title}
          </h3>
        </div>
        <span className="font-mono text-[10px] uppercase" style={{ color: "var(--vt-ink-faint)" }}>
          {role}
        </span>
      </div>
      <ul>
        {items.map((it, i) => (
          <li
            key={it.fn}
            className={`flex flex-col gap-1.5 py-5 ${i > 0 ? "border-t" : ""}`}
            style={{ borderColor: "var(--vt-line)" }}
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <code
                className={`font-mono text-[13px] font-semibold ${struck ? "line-through" : ""}`}
                style={{ color: tone }}
              >
                {it.fn}
              </code>
              <span
                className="rounded border px-2 py-0.5 font-mono text-[9px] uppercase"
                style={{ borderColor: edge, color: tone, background: "var(--vt-raised)" }}
              >
                {it.tag}
              </span>
            </div>
            <p className="text-[13px] leading-relaxed" style={{ color: "var(--vt-ink-dim)" }}>
              {it.body}
            </p>
          </li>
        ))}
      </ul>
    </div>
  )
}
