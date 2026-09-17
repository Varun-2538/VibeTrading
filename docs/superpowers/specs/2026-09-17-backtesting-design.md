# Backtesting strategy rules on seen and unseen data

**Date:** 2026-09-17
**Branch:** `feature/backtesting`, shipped in four slices, each merged to `main` and deployed on its own.

## Goal

A trader who has built a rule — in the Strategy panel, from a chat sentence, or from a chart-fellow
finding — can ask *would this have worked?* and get a professional-grade answer: does the signal
predict anything at all, what would trading it have returned, and does that result hold up on data the
settings were never tuned on.

The README already says that whether these patterns predict anything "is a backtesting question this
project has not yet answered". This feature answers it, including when the answer is *no*.

## Decisions taken

| Question | Decision |
|---|---|
| What counts as a result | **Both** a signal study (forward returns versus a baseline) and a full trade model (exits, fees, equity). |
| Seen vs unseen | **Tune on seen, verify on unseen.** History splits 70/30; a grid is searched on seen only; the one chosen setting runs once on unseen. |
| Timeframes and depth | **5m: 6 months, 15m: 1 year, 1h: 3 years, 1d: all available**, for the nine listed pairs. |
| Compute | **Keep the e2-small.** Backtests are queued background jobs; one runs at a time. |
| Where in the UI | **A Backtest button on any rule** — Strategy panel rules, chat draft cards, fellow Alert drafts — opening a report sheet. |
| Who can run one | Wallet session required; each wallet sees only its own jobs; one queued-or-running job per wallet. |

## What is backtested

Rules as they exist today: `PatternRuleParams`, `LiquidityRuleParams`, `SequenceRuleParams`, validated by
the same `RuleCreate` schema that arms them. A rule does not need to be armed to be backtested. The
orchestrator's `trading_strategy` output is prose and is out of scope.

## Measured constraints

Detector cost per bar on a 500-bar trailing window, measured on the development laptop: levels 0.45 ms,
patterns 8.7 ms, sequence (candle + RSI) 6.6 ms, sequence (structure step) 16 ms. The e2-small's shared
vCPU is roughly 3–4× slower. A pattern replay of 1h × 3 years (~26k bars) is therefore ~10–15 minutes
on production, 5m × 6 months (~52k bars) ~25–30 minutes. Tuning cannot multiply that, which is what the
candidate tape (below) is for.

## Architecture

```
Binance klines (paged) ──► candles_history  (TimescaleDB hypertable)
                              symbol, timeframe, time, OHLCV
                              backfilled once; topped up hourly

POST /api/backtests ──► backtest_jobs  (owner, request, status, stage, progress)
                              │
                              ▼
backtester worker ──► 1. load history; split at 70% into seen | unseen
   (own container,    2. replay bars ─► candidate tape (cached: signal_tapes)
    same image,       3. signal study on seen and unseen, each against its baseline
    low CPU priority) 4. tune exits + filters on the seen tape only
                      5. run the chosen setting once on unseen
                      6. write the report ─► backtest_jobs.report
GET /api/backtests/{id} ──► status, progress, report
```

**Why a separate worker.** A 30-minute replay inside the API process would share CPU with the API and
with the minute-by-minute alert sweep. In its own container at low priority (`cpu_shares`, `nice`) it
cannot delay a live alert, and a crash does not take the API down.

**Why reuse the live matchers.** The replay calls the same `_match_pattern`, `_match_liquidity` and
`_match_sequence` the alert engine uses, on the same trailing window length (`params.lookback`). A
backtest therefore measures what the alert would have done. A faster vectorised reimplementation was
rejected: the day it disagrees with the live engine, the backtest is lying about the user's alerts.

### Targeted refactor: a pure firing decision

`RuleEngine.evaluate_rule` interleaves the decision (persistence streak, cooldown, dedup) with database
writes (`RuleRepository.set_pending`) and the wall clock (`datetime.now()` for cooldown). Replay needs
the decision without either. It is extracted into a pure function:

```python
@dataclass
class FiringState:
    pending_identity: Optional[str]
    pending_seen: int
    last_bar_time: Optional[datetime]
    last_fired_at: Optional[datetime]
    fired_keys: set          # dedup keys, replay only

def decide(state, matched, bar_time, *, persist_bars, cooldown_secs, now) -> Tuple[FiringState, Optional[str]]
```

`evaluate_rule` keeps its signature and behaviour: it calls the matcher, then `decide(..., now=wall
clock)`, then persists the new state. Replay calls `decide(..., now=bar close time)` and keeps state in
memory. Existing `test_rule_engine.py` must pass unchanged; that is the refactor's acceptance test.

## Components

### 1. History store (`slice 1`)

- **Migration `004_candles_history.sql`:** hypertable `candles_history(symbol, timeframe, time
  timestamptz, open, high, low, close, volume)`, primary key `(symbol, timeframe, time)`.
- **`services/history_service.py`:** `backfill(symbol, timeframe, since)` pages Binance
  `/api/v3/klines` with `startTime`, 1000 bars per request, oldest to newest; upserts; resumes from the
  newest stored bar; retries with exponential backoff on HTTP errors and 429; sleeps between pages to
  stay far below Binance weight limits. `load(symbol, timeframe, start, end)` returns candles in the
  existing `{time ms, open, high, low, close, volume}` shape. Only closed bars are stored.
- **Depth per timeframe:** `HISTORY_DEPTH = {"5m": 183 days, "15m": 365 days, "1h": 3 × 365 days, "1d":
  None}` (None = since listing).
- **Top-up:** an APScheduler job in the worker, hourly, appends new closed bars for every pair and
  timeframe; trims rows older than the depth.
- **Coverage:** `GET /api/history/coverage` → per pair and timeframe `{first, last, bars, gaps}`. A gap
  is any missing expected bar time; reported, not filled with invented bars.
- **CLI:** `python -m scripts.backfill_history [--symbol] [--timeframe]` for the first fill.

### 2. Replay and candidate tape (`slice 2`)

- **Second targeted refactor: candidates, then a filter.** Each matcher is split in two, and the live
  engine is rewritten to call both, so live and replay share one code path:
  - `pattern_candidates(params, patterns)` / `liquidity_candidates(params, levels, closes)` return
    **every** match that passes the non-filter conditions, in the order the matcher already ranks
    them, each with its filter value (`confidence`, or level `strength` and `distance_pct`);
  - `first_passing(candidates, filters)` returns the first candidate that passes `min_confidence`, or
    `min_strength` and `proximity_pct` — exactly what `_match_pattern` / `_match_liquidity` return
    today. Sequence rules have no filter; their candidate list is the single match or empty.
- **`backtest/replay.py`:** `replay(candles, rule_params, *, warmup, progress)` walks bar index `i` from
  `warmup` to the end. At bar `i` the detectors receive exactly
  `candles[max(0, i+1-lookback) : i+1]` — never a later bar. The output is the **candidate tape**: per
  bar, the ordered candidates `{identity, direction, provisional, confidence | strength, distance_pct,
  evidence_summary}`, and the bar's time and close. No filter and no `decide()` has been applied yet.
- **Signals from the tape:** `signals(tape, filters, *, persist_bars, cooldown_secs)` walks the tape,
  takes `first_passing` per bar and runs `decide()` with bar-time clocks. It is cheap (microseconds per
  bar), so tuning over filter values never replays detectors.
- **What the tape depends on:** symbol, timeframe, the rule's *detector* parameters (pattern
  `strictness/source/scale/kinds/states`, liquidity `side/event/proximity_pct`, sequence
  `steps/within_bars`, `lookback`), and the history's last bar time. Filters (`min_confidence`,
  `min_strength`), `persist_bars` and `cooldown_secs` are not in the key. *(Slice 2 decision:)*
  `proximity_pct` is a detector parameter — approach candidates are recorded only within it —
  because recording every level on every bar made tapes tens of megabytes.
- **Tape cache:** table `signal_tapes(key text, created_at, bars integer, rows bytea)` holding
  gzip-compressed JSON. Re-tuning the same rule skips replay. Rows older than 14 days are deleted by
  a job every 6 hours. Topping up history never invalidates a tape: the key includes the history's
  last bar time, so a job over newer history computes a new key. Only complete tapes are stored.
- **Progress:** written to `backtest_jobs.progress` before each 500-bar chunk.

### 3. Signal study (`slice 2`)

For each tape signal at bar `i` with direction `d ∈ {+1 long, −1 short}` (neutral signals use the
job's neutral handling; skipped signals are excluded from the study and counted):

- forward return at +1, +5, +10, +20 bars: `d × (close[i+k] / close[i] − 1)`;
- maximum favourable and adverse excursion over the next 20 bars, in ATR(14) units at bar `i`.

**Baseline:** the same forward returns over *every* bar in the same period, taken in the same
direction mix as the signals (a 70%-long signal set is compared with a 70%-long baseline). **Edge** =
signal mean − baseline mean, with a 95% bootstrap confidence interval (2,000 resamples, fixed seed so
reports are reproducible). Reported separately for seen and unseen.

*(Slice 2 decisions:)*

- **Distinct setups:** the study counts the first fire of each setup identity. A live rule re-fires on
  every bar its setup persists; counting those fires as separate observations would make the interval
  falsely narrow. The report shows both fires and setups.
- **Boundary:** a seen signal whose horizon reaches the split is excluded at that horizon, so no seen
  statistic reads an unseen price.

### 4. Trade model (`slice 3`)

`backtest/trades.py`, pure:

- **Direction:** bullish → long, bearish → short. Neutral → the job's `neutral` setting: `skip`
  (default), `long` or `short`.
- **Entry:** open of bar `i+1`, adjusted by slippage against the trade (default 0.02%).
- **Exits, first hit wins:** stop (`stop_atr` × ATR(14) at the signal bar, or `stop_pct`), target
  (`target_r` × risk, or `target_pct`), `max_bars` held, optional `exit_on_opposite` signal.
- **Fills:** a bar that touches both stop and target counts the **stop**. A bar that opens beyond the
  stop fills at its open. Same for the target when it opens beyond it (fill at open, which is better —
  honest in both directions). Exits by `max_bars` or opposite signal fill at the next bar's open.
- **Fees:** `fee_pct` per side on notional, default 0.1%.
- **One position at a time.** Signals during an open trade are counted as `skipped_in_position`.
- **Sizing:** risk 1% of equity per trade at the stop distance, compounded; no leverage cap beyond
  notional ≤ 100% of equity (a stop tighter than 1% is sized down to full notional). Every trade
  records its result in R and in %.
- Shorts are labelled in the report as requiring futures or margin.

*(Slice 3 decisions:)*

- **Trades come from distinct setups**, like the study: a setup is traded once, not re-entered on every
  bar its alert repeats.
- A signal on the bar before a trade's open-price exit is skipped: the position is still held at that close.
- A signal whose stop cannot be sized (ATR not yet available, or zero) is counted in `skipped_no_room`
  together with signals too late to enter.
- Equity is marked to market at every close, so drawdown includes losses on open trades.
- The equity chart draws unseen continuing from seen's final equity; each period's metrics start at 1.0.
- Chart marks are offered only for trades inside the chart's loaded 1,000 candles, and markers whose bar
  is not loaded are never drawn — the markers plugin would otherwise snap them to the nearest candle.

### 5. Metrics (`slice 3`)

`backtest/metrics.py`, pure, computed separately for seen and unseen: trade count, win rate, average
win R, average loss R, expectancy R, profit factor, total return %, max drawdown %, Sharpe (from
per-bar equity returns, annualised by timeframe), exposure %, longest losing streak, buy-and-hold
return over the same bars. Equity curve (downsampled to ≤ 1,000 points) and the full trade list
`{entry_time, entry, exit_time, exit, direction, exit_reason, r, pct}`.

**Honesty flags** in the report:

- fewer than 30 trades in a period → `too_few_trades`;
- unseen expectancy below 50% of seen, or of opposite sign → `likely_overfit`;
- signal-study edge CI contains zero → `no_edge_detected`;
- the number of grid settings tried, always.

### 6. Seen/unseen tuning (`slice 4`)

- **Split:** by bar time at `split` (default 0.70) of the loaded history, after warm-up. The replay
  runs once over the whole history (indicators need continuity across the boundary); the tape is then
  cut at the split time. A trade opened in seen that is still open at the boundary is closed at the
  boundary bar's open and excluded from unseen.
- **Grid (defaults):** `stop_atr ∈ {1, 1.5, 2}` × `target_r ∈ {1, 2, 3}` × `max_bars ∈ {10, 20, 40}` ×
  the rule's filter (`min_confidence ∈ {60, 70, 80}` for patterns; `min_strength ∈ {weak, medium,
  strong}` for liquidity; none for sequences). User-editable; capped at 200 combinations; a request
  over the cap is a 422.
- **Objective:** highest seen expectancy R among settings with ≥ 30 seen trades; ties broken by lower
  seen max drawdown. If no setting reaches 30 trades, the one with the most trades is chosen and the
  report is flagged `too_few_trades`.
- **The unseen lock:** `tune()` is passed the seen tape and seen candles only — the unseen slice is not
  in its arguments. The chosen setting is then evaluated on unseen exactly once. The report shows the
  top 5 on seen and the unseen result for the chosen one only.
- Without tuning (`tune: false`) the job's own exit plan is run on both periods.

*(Slice 4 decisions:)*

- **Tuning is on by default** in the sheet, because a cached tape makes it cheap - and every report states how
  many settings were tried, so a tuned number is never presented as an untuned one.
- **The grid is searched by filter group:** signals depend only on the rule filter and exits only on the plan,
  so each filter's signals are derived from the tape once and reused across exit combinations.
- **Percentage stops and targets are not tuned** - a grid mixing ATR and percentage stops would not compare
  like with like. They remain available for a single untuned run.
- **`tuning.top` reports seen metrics only.** Running the runners-up on unseen data would make unseen a second
  tuning set.
- Repeating a backtest after new candles arrive still replays from scratch, because the tape is keyed to the
  newest candle. Extending a tape bar by bar is a later slice.

## API

All routes require the wallet session (`require_owner`), and jobs are scoped to the owner.

| Route | Behaviour |
|---|---|
| `POST /api/backtests` | Body: `rule` (`RuleCreate`-shaped: symbol, timeframe, params, cooldown_secs, persist_bars), `exit` (plan above), `neutral`, `tune` (bool), `grid` (optional), `split` (0.5–0.9). Validates, checks coverage, returns `{id}`. **422** schema error or grid over cap; **409** no history for that pair/timeframe; **429** the wallet already has a queued or running job. |
| `GET /api/backtests/{id}` | `{status, stage, progress, error, report}`. Status ∈ `queued, replaying, studying, tuning, done, failed, cancelled`. |
| `GET /api/backtests` | The wallet's last 20 jobs, without full reports. |
| `DELETE /api/backtests/{id}` | Cancels a queued/running job (worker checks between chunks) or deletes a finished one. |
| `GET /api/history/coverage` | Public; per pair and timeframe coverage. |

**Migration `005_backtests.sql`:** `backtest_jobs(id uuid, owner_key, created_at, started_at,
finished_at, status, progress, request jsonb, report jsonb, error text)` and `signal_tapes`. The
status carries the stage; there is no separate stage column.

**Worker loop:** claims the oldest queued job with `SELECT … FOR UPDATE SKIP LOCKED`; on start, every
job in a running status is returned to `queued` — there is one worker, so a running status after a
restart always means an interrupted job. A job whose replay finished before the interruption reuses
the cached tape; a partial replay starts again. One job at a time.

## UI

- **Backtest button** on Strategy panel rules, chat draft cards and fellow Alert drafts. Works on
  unarmed drafts. Requires the wallet session; otherwise shows the existing sign-in gate.
- **Report sheet** (`components/backtest-sheet.tsx`):
  1. *Setup:* exit plan (stop, target, max bars), neutral handling where the rule can be neutral, "Tune
     on seen data" toggle (on by default), split slider, fees and slippage under "Costs".
  2. *Running:* stage and progress ("Replaying BTCUSDT 1h — 42%"), cancel.
  3. *Report:* a one-line verdict ("Unseen: +0.18R over 41 trades — 60% below seen, likely
     overfit"); the signal study with edge and CI; seen and unseen metrics side by side with flags; the
     tuning top 5; the equity curve with the seen | unseen boundary; the trade list with **Mark on
     chart**, which lifts trade entries and exits as `BarMark`s through the existing marks path.
- A **recent backtests** list in the Strategy panel, so a report survives closing the sheet.
- **Risk page:** past results on seen and unseen data are not a forecast; costs and fills are modelled,
  not guaranteed; tuned results are selected from many tries.
- **Architecture page:** a paragraph on replay-with-live-matchers, the tape and the unseen lock.

## Error handling

- Missing or insufficient history → 409 at submit with the reason ("15m BTCUSDT history starts
  2025-09-17; this rule needs 300 warm-up bars").
- Binance failures during backfill → retry with backoff; resume from the last stored bar; the gap
  shows in coverage.
- Worker crash or deploy mid-job → the worker requeues it on start; a completed tape in the cache
  avoids repeating finished replay work.
- A job over one hour of runtime is failed with `timeout`, so a pathological rule cannot hold the queue.

## Testing

Offline, deterministic, no network:

- **Refactor safety:** `test_rule_engine.py` passes unchanged after extracting `decide()` and splitting
  the matchers; new unit tests for `decide()` cover persistence streaks, cooldown by bar time and dedup;
  `first_passing(candidates(...), filters)` equals the old matcher's output on the existing fixtures.
- **No look-ahead:** replay a history, then append fabricated future bars that would change every
  detector's output; assert tape rows before the appended bars are byte-identical.
- **Parity:** for random cut points, the tape's signal at bar `i` equals `evaluate_rule(dry_run)` on
  `candles[:i+1]` with the same state.
- **Fills:** hand-built bars for stop-and-target in one bar (stop wins), gap through stop (fill at
  open), gap through target, max-bars exit, opposite-signal exit, fees and slippage arithmetic.
- **Metrics:** against hand-computed trade lists (expectancy, profit factor, drawdown, streak).
- **Unseen lock:** `tune()`'s signature has no unseen argument, and a test asserts the tuner never
  reads a bar time at or past the split.
- **Honesty:** on synthetic random walks, the signal study's edge CI contains zero for a doji rule and
  a W rule, and no tuned setting's unseen expectancy is flagged as an edge.
- **History:** paging assembles contiguous bars from canned Binance pages; resume starts after the last
  stored bar; gaps are detected.
- **API:** 401 without session, 429 on a second job, 409 without coverage, owner scoping.

## Slices

1. **History store** — migration 004, history service, backfill CLI, hourly top-up, coverage endpoint.
   Ships with the first fill running on production.
2. **Replay and signal study** — `decide()` and candidates refactors, worker container, job and tape tables, replay,
   signal study with baseline, API, Backtest button and a minimal report (study only).
3. **Trade model and metrics** — exits, fills, fees, sizing, metrics, equity curve, trade list, marks.
4. **Seen/unseen tuning** — split, grid, objective, unseen lock, verdict and honesty flags, recent
   backtests list, risk and architecture pages.

## Out of scope

Walk-forward optimisation, portfolio backtests across several rules, open interest and funding data,
executing trades, the orchestrator's prose strategies, and timeframes other than 5m/15m/1h/1d.
