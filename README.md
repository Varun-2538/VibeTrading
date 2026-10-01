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
Engine `e2-medium` in `asia-south1-a`. Live prices reach the browser over a
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
