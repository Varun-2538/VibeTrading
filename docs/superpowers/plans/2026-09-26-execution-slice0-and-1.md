# Execution slices 0 and 1: close the holes, then share the trade maths

**Date:** 2026-09-26 · design: `specs/2026-09-26-autonomous-execution-design.md`.
Nothing executes yet. These two slices exist so that the slice which does cannot
be unsafe.

## Slice 0 — the holes

### A manual endpoint that would have become a trade trigger

`POST /api/rules/{id}/test?emit=true` calls `RuleEngine.fire()` straight from an
HTTP handler — outside the sweep, with no rate limit anywhere in the app. Fine
while the only action is an alert; the day `dex_trade` is registered it is a way
to place trades by request. It now returns **409** when the rule's action is
anything but `alert`. Testing the rule is still allowed, because the refusal is
about emitting, not about evaluating.

### The status write was a lost update waiting to happen

`set_action_result` was an unconditional `UPDATE`. One writer making one attempt
cannot lose anything, which is all an alert does. Once an action hands the fire to
another process, a late attempt finishing afterwards would overwrite the outcome
that process wrote — `failed` quietly becoming `sent`, hiding an abandoned trade.
Replaced by `set_action_result_if(event_id, expected, status, result) -> bool`,
which moves the row only from a status the caller expected and returns False when
it had already moved on. `fire()` now writes all three of its outcomes through it,
from `('pending',)` only.

The status vocabulary is a constant in `services/actions/base.py` rather than
literals scattered through the code, and it gains `queued`: not a delivery, but
"handed to another process, which will move this row itself".

### Three processes booting into the same schema

`bootstrap_schema` ran each migration on its own pooled connection, and
`CREATE TABLE IF NOT EXISTS` is not race-free — concurrent creation can raise a
unique violation on `pg_type`. The API catches that and survives; `worker.py` did
not and would crash-loop. Now the whole run happens on one connection under one
advisory lock (`BOOTSTRAP_LOCK`, a fixed integer rather than `hashtext`, which is
undocumented), released in a `finally` — because a lock leaked by one bad deploy
would wedge every other process at boot, permanently. The worker's call is also
guarded.

### Two things the execution layer will need

- **`Database.transaction()`**, which did not exist: every helper acquires its own
  connection, so two of them could no more be atomic than two separate requests.
  Callers get the asyncpg connection itself, deliberately — pretending a pooled
  helper is transactional is the mistake this prevents.
- **`db_pool_min` / `db_pool_max` settings.** The pool was hardcoded at 5/20 in
  every process. Postgres allows 100 connections and there will be three
  processes; the backtester now asks for 1/4 in `docker-compose.prod.yml`, since
  one poll every five seconds needs nothing like the API's pool.

### Found while writing the tests

In `fire()`, the unknown-action check precedes the provisional gate. Both skip, so
nothing is at risk — but it means a test asserting "a provisional signal cannot
reach a spender" proves nothing unless a spender is actually registered. The test
registers one, and asserts it was not called.

## Slice 1 — `services/trade_plan.py`

The same extraction that produced `services/rule_decision.py`: the pure half moves
to `services/`, `backtest/` imports it, and the live executor will call the same
functions. `bar_exit` is the load-bearing one — `trades.py::_exit` loops over it
and a monitor will call it once per closed bar, so first-hit-wins,
worse-case-inside-a-bar and gap-fills-at-the-open exist once.

Also `bracket()` (entry, stop distance, target, size), `notional_fraction`,
`trade_return`, `frictionless_return`, `in_r`, `time_exit_bar_index`,
`notional_usd`, and `ATR_BARS`, which `backtest/study.py` now re-exports instead of
defining — a stop measured over a different window than the one that was
backtested is a different stop.

Scalars, not candle dicts: a grid search calls `bar_exit` millions of times.
Measured after the change, 200 × `simulate` over 3,000 bars with 412 signals takes
**0.65 s**, so the indirection costs nothing that matters.

### Two traps the extraction documented rather than fixed

- `notional_fraction` is `min(1.0, (risk_pct/100) / (dist/entry))`. The clamp means
  a stop wider than `risk_pct` of price risks **less** than was asked for. A live
  executor computing size from `risk_pct` naively would take *more* risk than the
  report measured, so it must call this function.
- `ExitPlan.max_bars` allows 500, which on `1d` is a sixteen-month hold. Not
  changed here; it has to be capped at arming time.

### Anti-drift

`PARITY_VERSION` is stamped into `report["meta"]` (mirrored as optional on the
client type) and will be required to match before a rule can be armed for
execution. `BEHAVIOURAL_FIELDS | COST_FIELDS == set(ExitPlan.model_fields)` is
asserted by a test, so a new knob on the exit plan cannot be added without someone
deciding whether live obeys it.

## The proof

`tests/test_backtest_trades.py` passes **completely unchanged** — that file already
pins every subtle fill case, and no better regression net could be written for this
extraction.

`tests/test_trade_plan.py` then tests what that file cannot see: a `live_exit()`
driver that consumes one bar at a time, holding a deadline instead of a loop
counter, with no access to future bars — the shape a monitor has — reaching the
same exit index, price and reason as `simulate()` over the whole array. Across 8
random-walk seeds × 4 exit plans × both directions, 40+ real trades per case. A
circular test would have been `_exit` versus `bar_exit`; this is the usage pattern
that can actually diverge.

Backend 553 tests (was 486), frontend 71, `next build` clean.

## Next

Slice 2 is long-only backtests, which the spot venue needs as evidence. Slice 3 is
the typed action config, the policy table, the preflight gate and the arming API —
still with nothing that executes.

---

# Slice 2 — long-only backtests

A Uniswap pool cannot short: a position is the asset or it is stablecoins. But
`backtest/trades.py` has always simulated shorts, so every report to date counts
trades that pool could never have taken. As evidence for spot execution such a
report is not conservative, it is wrong — and the preflight gate will refuse it.

`BacktestCreate` gains `sides: Literal["both", "long", "short"] = "both"`.

**Two separate questions, kept separate.** `neutral` is how a signal with *no
direction of its own* is read (a doji, an inside bar, a volume spike, a squeeze).
`sides` is which directions *the venue* can take at all. Both decide whether a
trade happens rather than how it ends, so neither belongs on `ExitPlan`; both now
live in `services/trade_plan.signed_direction(direction, neutral, sides)`, which
replaced `study.signed` — one mapping, used by the study and by the trades, so a
live executor cannot answer it differently.

**The subtle part, and the reason the filter is not in the mapping call.**
`simulate` maps directions *without* the side filter and refuses the side
explicitly in its loop. That is deliberate: `exit_on_opposite` scans the mapped
list for an opposing signal, and on a long-only venue a bearish signal is not a
trade but is still a reason to be out. Filtering before the scan would silently
hold the position through the exact signal the user asked to exit on. There is a
test for it, because it is the kind of thing that looks like a rounding error in a
report and is actually a held loser.

Refusals are counted as `skipped_side`, not folded into `skipped_neutral`: "no
direction of its own" and "a short on a spot pool" are different reasons and only
one of them is about the venue. The report carries the count, the sheet renders it
next to the other skips, and `meta.sides` records what was measured.

The default stays `both`, so no existing report changes meaning. Instead the
Strategy panel's Backtest sheet gains a **Directions to trade** row, and when
`both` is selected it says plainly that a spot pool cannot short and that a report
justifying on-chain execution has to be measured long only. Enforcement is the
arming gate's job, not the backtester's — measuring a short strategy is a perfectly
reasonable thing to want.

Backend 562 tests, frontend 72, `next build` clean.
