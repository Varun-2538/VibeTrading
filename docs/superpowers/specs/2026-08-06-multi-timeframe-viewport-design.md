# Multi-timeframe charting and viewport-scoped analysis

Date: 2026-08-06
Status: approved, not yet implemented
Slice: 1 of 4

## Why

VibeTrading is to become a platform where a trader picks any timeframe, looks at
any part of the chart, and asks in plain English what is happening there —
liquidity levels, chart patterns (W/M, head and shoulders, flag and pole, cup and
handle), and market phase (accumulation, distribution, consolidation).

Every one of those features needs two things that do not exist yet:

1. Candles at timeframes other than 1h.
2. A way for the chart to tell the backend which candles are on screen.

This slice builds exactly those two things and nothing else. It is useful on its
own — levels become per-timeframe and follow the view — and it is the seam every
later slice plugs into.

## Scope

In:

- Timeframes 1m, 5m, 15m, 1h, 1d.
- Pan and zoom, with analysis following the visible window.
- Liquidity levels recomputed for the visible window of the selected timeframe.

Out (later slices):

- Pattern detection (slice 2: W/M; slice 3: the rest).
- Market phase classification (slice 4).
- Any user-authored strategy editor.

## Decisions already taken

**Viewport model: zoom and pan, analysis follows the view.** The alternative — a
fixed window per timeframe — was rejected because a pattern that scrolls off the
edge would simply cease to exist, and "only in the visible time frame" would be
a statement about what we happened to load rather than about what the trader can
see.

**Chart engine: TradingView Lightweight Charts (MIT).** Recharts has no pan, zoom
or crosshair and renders every candle as a React node, which does not survive the
candle counts a 1m chart needs. Lightweight Charts also exposes
`timeToCoordinate()` / `priceToCoordinate()`, which lets an SVG overlay draw
pattern geometry in exact chart coordinates, and
`subscribeVisibleLogicalRangeChange()`, which is precisely the viewport signal
this slice exists to provide.

**Pine Script is not an option.** Pine runs only inside tradingview.com. Neither
Lightweight Charts nor the Advanced Charts library executes it (Advanced Charts
takes custom studies in JavaScript). Detection is therefore implemented in our
own stack. Published Pine implementations of these patterns are still useful as
reference for the detection rules.

## Architecture

### CandleService — one supplier of candles

A new backend service becomes the single source of candles for both the chart and
every analysis path.

```
CandleService.get_candles(symbol, timeframe, limit) -> list[Candle]
```

- Fetches from Binance through the existing `BinanceFetcher`, which already maps
  every interval we need.
- Caches in Redis, TTL per timeframe: 1m→20s, 5m→60s, 15m→3m, 1h→5m, 1d→15m.
- Does not write to Postgres. Storing 1m candles for nine symbols would grow the
  database quickly and nothing in this slice reads it back.

The single-supplier rule is the point of the service. If the chart drew candles
from one source and the detectors analysed another, patterns and levels would be
marked at prices that do not match what the trader sees. Any drift here is a
correctness bug in every later slice, so it is designed out rather than managed.

### Levels move onto CandleService

`MarketDataService.detect_liquidation_levels` currently reads 1h candles from
Postgres. It gains a `timeframe` argument and sources candles from
`CandleService`, so levels agree with whatever chart is on screen.

The existing 1h ingest scheduler, the `ohlc_data` table and `GET /api/ohlc/{symbol}`
are left alone. Nothing that works today changes behaviour.

### Endpoints

```
GET  /api/candles/{symbol}?timeframe=1m|5m|15m|1h|1d&limit=1000
POST /api/analysis/levels   { symbol, timeframe, from, to }
```

`from` and `to` are unix millisecond bounds of the visible window. Later slices
add sibling endpoints taking the same request shape:

```
POST /api/analysis/patterns { symbol, timeframe, from, to, kinds: [...] }
POST /api/analysis/phase    { symbol, timeframe, from, to }
```

Fixing that request shape now is the main forward-looking decision in this slice.

### Frontend

`price-chart.tsx` is rewritten on Lightweight Charts and restyled to the existing
palette: neutral hollow/filled candles, mint reserved for live signals, blue and
orange for support and resistance (validated for colour-blind separation, so not
changed).

- Timeframe selector: 1m / 5m / 15m / 1h / 1d.
- Live ticks continue to come from the Binance kline websocket for the selected
  interval.
- An absolutely-positioned SVG overlay sits above the canvas, positioned through
  the chart's coordinate API. Levels draw there now; pattern geometry draws there
  later.
- Visible-range changes are debounced 250ms before re-requesting analysis.

## Data flow

```
timeframe change / pan / zoom
        |
        v
GET /api/candles          -> CandleService -> Redis hit? -> Binance
        |
        v
chart renders candles, reports visible [from, to]
        |
        v (debounced 250ms)
POST /api/analysis/levels -> CandleService (same cache) -> detector
        |
        v
SVG overlay draws levels in chart coordinates
```

Both requests go through `CandleService`, so the analysed candles are by
construction the rendered candles.

## Error handling

- Binance unreachable or rate limited: endpoint returns 502 with a plain message;
  the chart keeps the candles it has, shows an inline notice, and retries with
  backoff. A stale chart is better than an empty one.
- Redis down: `CandleService` falls through to Binance directly. Slower, still
  correct — the cache is an optimisation, never a source of truth.
- Unknown timeframe: 400 listing the accepted values.
- Empty visible window (zoomed past the data): analysis returns an empty result
  rather than an error; the overlay clears.

## Testing

Backend:

- `CandleService` maps each timeframe to the right Binance interval.
- A second call inside the TTL is served from cache and does not hit Binance.
- Redis failure still returns candles.
- Level detection over a fixed candle fixture returns known levels, and every
  support sits below spot with every resistance above it.
- `/api/analysis/levels` honours `from`/`to` — candles outside the window do not
  influence the result.

Frontend:

- Each of the five timeframes loads, renders and streams.
- Panning changes the reported visible range and triggers exactly one debounced
  analysis request, not one per frame.
- Switching timeframe cancels in-flight requests for the previous one.

## Done when

Switching to 1m loads roughly 1000 one-minute candles that stream live and pan and
zoom smoothly. Asking for liquidity levels returns levels computed from the 1m
candles currently on screen. Panning back an hour recomputes them for that window.
The same holds on 5m, 15m, 1h and 1d.
