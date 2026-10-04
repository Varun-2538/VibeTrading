# VibeTrading

Technical analysis that only looks at the candles you are looking at.

**Live:** [vibetrading.club](https://vibetrading.club) · **API:** [api.vibetrading.club/docs](https://api.vibetrading.club/docs)

VibeTrading reads recent candles for nine crypto pairs, finds the price levels
the market keeps returning to and the double bottoms and double tops forming in
them, and draws both on the chart. Analysis is scoped to the visible window, so
panning or zooming re-analyses exactly what is on screen rather than a fixed
lookback nobody chose.

No signup, no accounts, free to use.

---

## Rules that trade, in a vault you own — on Robinhood Chain and Arbitrum One

A rule built in the app can do more than alert: armed to trade, it opens and closes
positions **inside a contract the user deploys and owns**, holding their own USDG or
USDC. We run the bot; the contract is what makes that survivable.

- **We can never withdraw.** The operator key can open a position and close one.
  There is no function by which it moves money out, changes the router or the
  oracle, raises a cap, or moves a stop. The owner withdraws and revokes us at any
  time, on-chain, without asking.
- **The stop lives in the contract.** Stop, target and deadline are written at open
  and are immutable. Exits are **permissionless**: `closeIfStopped`,
  `closeIfTargetHit` and `closeIfExpired` revert unless the condition is true on a
  Chainlink price, and pay a small bounty to whoever calls them. Our executor is the
  fastest caller; if it is down, anyone else is paid to be. *Entries depend on our
  uptime. Exits do not.*
- **Oracle authorises, minimum-out protects.** Every swap must return at least the
  Chainlink price less the owner's slippage, so a caller cannot route an exit
  through a manipulated pool.
- **A backtest is mandatory.** A rule is armed only against a backtest of that exact
  rule whose *unseen* half clears a bar the user sets, after pool fees and gas.
- **Capped while unaudited.** $500 per vault, a constant in the factory.

### Deployed (mainnet)

| | Address | Explorer |
|---|---|---|
| VaultFactory · **Robinhood Chain** (4663) | `0x04C96936670c38982D1e7eF23caDd84d6891c818` | [Blockscout](https://robinhoodchain.blockscout.com/address/0x04C96936670c38982D1e7eF23caDd84d6891c818) · [Sourcify, exact match](https://repo.sourcify.dev/4663/0x04C96936670c38982D1e7eF23caDd84d6891c818) |
| VaultFactory · **Arbitrum One** (42161) | `0x04C96936670c38982D1e7eF23caDd84d6891c818` | [Blockscout, verified](https://arbitrum.blockscout.com/address/0x04c96936670c38982d1e7ef23cadd84d6891c818) |

| Chain | Dollar | Markets |
|---|---|---|
| Robinhood Chain | **USDG** (Paxos) | ETH, and **Robinhood Stock Tokens: NVDA, TSLA, AAPL, SPY, QQQ** |
| Arbitrum One | USDC | ETH, BTC |

**Stock Tokens keep market hours; the vault knows it.** A Stock Token's pool trades
around the clock, but its Chainlink feed is silent from Friday's close to Sunday
night. Each market therefore carries its own oracle-age limit, immutable in its
vault — 26 hours for crypto, 96 for US equities, never more than a 4-day ceiling.
Over a weekend every swap is priced against the last market answer, so a move
beyond the owner's slippage makes a swap refuse rather than fill badly.

### A real trade, on mainnet, closed by a stranger

One position in an NVDA vault on Robinhood Chain, on Sunday 2026-10-04 - with the
stock market closed and NVDA's Chainlink feed 36 hours old, inside the stock
market's 96-hour rule. The entry was sent by hand with the executor's key (in
production a rule's signal sends it); the exit was pushed by a wallet that is
neither the owner nor us, with our executor not involved.

| Step | Who | Transaction |
|---|---|---|
| Vault deployed for NVDA, disclosure hash stored | owner | [`0x97a0…2b50`](https://robinhoodchain.blockscout.com/tx/0x97a072142e53020abef128429f3627e34b1d96f6b943ead1e0f5a089f50e2b50) |
| **Open**: 2 USDG → 0.008519 NVDA at $235.00; stop $211.50, target $282.00, 10-minute deadline written into the vault | executor (operator) | [`0x5b59…df0d`](https://robinhoodchain.blockscout.com/tx/0x5b593eb33990944d8ae1f56c1e06fa993f87fe4809c19b8f3dc442fce955df0d) |
| An early `closeIfExpired` / `closeIfStopped` from the stranger | stranger | refused by the vault: `NotTriggered()` |
| **Close** on expiry: 0.008519 NVDA → 1.998682 USDG; **1 USDG bounty** paid to the caller | stranger | [`0x6cf8…1c5b`](https://robinhoodchain.blockscout.com/tx/0x6cf82b8fcb8f6448544f621fad837c5d830d7d1eca942c45a5df42993e8a1c5b) |

Vault: [`0x99a0…99a5`](https://robinhoodchain.blockscout.com/address/0x99a038f8335ADfb5332aCB8e4c520FaCCf8b99a5). The
round trip cost 0.0013 USDG in pool fees on 2 USDG; the bounty is what the
permissionless exit costs, and it went to whoever pushed the button.

Live analytics: **[Dune dashboard](https://dune.com/vibetradingclub/org-data)** - vaults, deposits, positions, and who closed each one, from raw Robinhood Chain logs ([queries](analytics/dune/)).

### How it was tested

- `contracts/`: 30 offline tests, mostly refusals — the operator cannot withdraw,
  cannot move a stop, cannot exceed a cap; a stale feed authorises nothing; a fill
  worse than the oracle allows is refused even when the router lies about it.
- **Fork tests against both mainnets**, run before deploying: a full round trip on
  **every market** — deposit, grant, open through the real Uniswap pool at the real
  Chainlink price, refuse an early exit, and a stranger closing on expiry and being
  paid the bounty. On a Sunday, against weekend-silent stock feeds, all six
  Robinhood Chain markets and both Arbitrum markets pass.
- Backend: 781 tests, including exactly-once execution held by unique indexes, and a
  shadow mode that runs the same code path as live against real prices.

Details: [`contracts/README.md`](contracts/README.md).

### What is not done yet

- **Stock rules cannot be armed.** Signals are read from exchange candles, and no
  exchange we read lists stocks; a stock vault is traded by hand for now. Building
  candles from the Uniswap pools themselves is the next step.
- **Long only.** A spot pool cannot short.
- **Unaudited**, hence the $500 cap. The operator key is an environment variable;
  a KMS signer comes before any cap is raised.

---

## What it does

**Liquidity levels.** Clusters recent price action into the levels that have
actually been tested, and reports how many times each one was tested so strength
is measured rather than asserted.

**Double bottoms and tops.** Finds W and M patterns and marks each with where it
is in its life — `forming`, `approaching` the neckline, or `confirmed` by a close
beyond it. A setup is visible while it develops rather than only once it has
completed and given up most of its move.

**Two controls, because these are judgement calls.** *Scale* selects the size of
structure to look for (swing, scalp, or both); *strictness* sets the quality bar
within it. They are separate axes: bundling them made "small but precise" —
exactly what a scalper wants — impossible to ask for.

**A chat assistant** that answers questions about levels and patterns in plain
language.

---

## How the analysis works

Every threshold is expressed in **ATR**, never as a percentage of price. This is
the central design decision and it was learned the hard way: a fixed 2% rule is
calibrated for daily charts and breaks completely intraday. On BTC, the shoulder
tolerance used by widely-copied Pine scripts works out to 0.9 ATR on a daily
chart but **65 ATR on a 1-minute chart**, where it matches any two lows at all.
ATR-relative thresholds behave the same on every timeframe.

The detector is deterministic — pivot detection, ATR-scaled comparisons, and a
geometric score. There is no prediction model and no trained weights. A
confidence percentage decomposes into three measurable terms (how closely the
two shoulders match, how deep the pattern is, how symmetric its legs are), so
any score can be explained rather than trusted blind.

The language model is used **only** for the conversational interface. It never
computes a level or a pattern.

### An honest limitation

Run the detector over a random walk with no structure in it and it returns
roughly as many patterns as it does on real market data. This is a property of
chart patterns generally rather than a defect in this implementation — random
walks genuinely contain W-shapes — but it means **a mark is evidence of a shape,
not evidence of an edge**. Confidence describes how cleanly a shape matches its
geometric definition, not the probability that a trade works. Whether these
patterns predict anything is a backtesting question this project has not yet
answered.

---

## Architecture

```
Browser
  │
  ├─ vibetrading.club ......... Next.js 15 (App Router) on Vercel
  │                             Lightweight Charts + SVG pattern overlay
  │
  └─ api.vibetrading.club ..... Caddy (automatic TLS)
                                  │
                                  ├─ FastAPI (Python 3.11, Docker)
                                  │    ├─ analysis/  deterministic detectors
                                  │    └─ agents/    Cerebras, chat only
                                  ├─ TimescaleDB     candles, annotations
                                  └─ Redis           hot-path cache
```

Everything behind the API runs in Docker Compose on a single Google Compute
Engine `e2-small` in `asia-south1-a`. Live prices reach the browser over a
WebSocket direct from the exchange; historical candles are served by the API and
cached.

| Layer | Choice |
|---|---|
| Frontend | Next.js 15, TypeScript, Tailwind, Lightweight Charts, Vercel |
| API | FastAPI, Python 3.11, Pydantic, uvicorn |
| Analysis | Pure Python, no ML dependency |
| Database | TimescaleDB (PostgreSQL 15) — hypertables for time series |
| Cache | Redis 7 |
| Edge | Caddy 2, automatic TLS |
| Compute | Google Compute Engine, `asia-south1` |
| LLM | Cerebras (`gemma-4-31b`) via LangChain, chat only |
| Market data | Binance public REST + WebSocket |

---

## Running it locally

**Prerequisites:** Docker and Docker Compose, and a
[Cerebras API key](https://cloud.cerebras.ai/) (free tier is enough) if you want
the chat assistant. The charts and all analysis work without one.

```bash
git clone https://github.com/Varun-2538/smartTrade.ai.git
cd smartTrade.ai

cp .env.prod.example .env     # set CEREBRAS_API_KEY, TIMESCALE_USER, TIMESCALE_PASSWORD
docker compose up -d          # TimescaleDB, Redis, MCP server, API

cd frontend
npm install
npm run dev                   # http://localhost:3000
```

`docker-compose.yml` is the local stack; `docker-compose.prod.yml` is what runs
on the server and adds Caddy for TLS.

Verify the API:

```bash
curl http://localhost:8000/health
```

### Tests

```bash
cd backend
python -m pytest tests/ -q    # 77 tests
```

The pattern tests build synthetic W and M fixtures from line segments, so the
geometry is known exactly and assertions are made on prices rather than on
"something was found". Several tests exist because a real chart disagreed with
the detector — those regressions are documented in the test docstrings.

### Android app

The Play Store app is a Trusted Web Activity: Chrome rendering
`app.vibetrading.club` full-screen. Nothing is duplicated; a deploy to Vercel
updates the app.

```bash
npm install -g @bubblewrap/cli && bubblewrap doctor   # installs JDK 17 + Android SDK on first run
cd android
bubblewrap build          # asks for the upload keystore password; the JDK's bin must be on PATH
adb install app-release-signed.apk
```

Bump `appVersionCode` in `android/twa-manifest.json` and run `bubblewrap update`
before each upload to Play. `frontend/public/.well-known/assetlinks.json` must
list both the upload key and the Play App Signing key, or Chrome shows a URL
bar. Frontend unit tests: `cd frontend && npm test`.

---

## API

Analysis endpoints take the same window — `{symbol, timeframe, from, to}` — so
the chart can ask any question about exactly the candles it is showing.

| Endpoint | Purpose |
|---|---|
| `GET /api/candles/{symbol}` | OHLC candles, times in unix ms |
| `POST /api/analysis/levels` | Support and resistance in a window |
| `POST /api/analysis/patterns` | Double bottoms and tops in a window |
| `GET /api/analysis/strictness` | Available strictness, scale and source options |
| `POST /api/chat/ask` | Ask the assistant a question |
| `GET /api/timeframes` | Timeframes this deployment serves |
| `GET /health` | Service and dependency health |

Full interactive documentation at
[api.vibetrading.club/docs](https://api.vibetrading.club/docs).

Example:

```bash
curl -X POST https://api.vibetrading.club/api/analysis/patterns \
  -H "Content-Type: application/json" \
  -d '{"symbol":"BTCUSDT","timeframe":"1h","strictness":"balanced","scale":"both"}'
```

---

## Project layout

```
backend/
  analysis/         detectors — patterns.py is the W/M implementation
  controllers/      FastAPI routes
  services/         candle fetching, caching, market data
  agents/           Cerebras agents for the chat assistant
  repositories/     TimescaleDB access
  tests/            77 tests
frontend/
  app/              Next.js App Router — landing, /app, legal pages
  components/       price-chart, pattern-overlay, chat-panel
  lib/api.ts        typed API client
android/            Trusted Web Activity project (Bubblewrap); twa-manifest.json is the source of truth
store/              Play Store listing assets
docs/superpowers/   design specs written before each slice
```

---

## Status

Live and in active development. Pattern detection has been corrected several
times in response to real charts where it disagreed with a trader's reading; if
you find one, [dev@vibetrading.club](mailto:dev@vibetrading.club) is read by a
person.

**VibeTrading is not financial advice.** It places no trades, holds no funds,
and never asks for exchange API keys. See the
[risk disclosure](https://vibetrading.club/legal/risk).

Originally prototyped as *TradeSmart.AI* for the FutureStack 2025 hackathon, and
substantially rewritten since.

## Licence

MIT
