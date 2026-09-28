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

---

# Slice 3 — who may trade, decided before anything can

Still nothing executes. What this adds is the decision and its record: the schema
an execution config must satisfy, the gate it must pass, and the table that
remembers what the server agreed to. The global switch ships `FALSE`, every
account ships `off`, and no process reads the queue yet.

## `006_execution.sql`

Eight tables. The important ones are the constraints, not the columns, because
exactly-once has to be a property of the schema rather than of a Python check —
two processes reading before either writes is a race by construction:

| Constraint | Stops |
|---|---|
| `execution_positions_one_live` UNIQUE on (owner, rule, venue, market, mode) WHERE status is live | Two positions for one rule. Also what keeps live faithful to `simulate`, which holds one at a time. |
| `execution_intents_one_per_event` UNIQUE on event_id | A second sweep, or a replayed loop, queueing a fire twice. |
| `execution_intents_one_exit_per_position` UNIQUE on (position, kind) for exits | A monitor tick that runs twice queueing two flattens — the second of which opens a reverse position. |
| `execution_orders.client_order_id` UNIQUE | Two sends of the same venue write. The row is inserted *before* the call. |
| `execution_fills` UNIQUE on (venue, venue_fill_id) | A positions poll after a restart booking a fill twice. |

The one cycle — a position names the intent that opened it, an exit intent names
its position — is broken on the position side with no foreign key, deliberately,
because a mid-file circular constraint cannot be written idempotently.

`backtest_jobs` gains `rule_id`, so the gate finds a rule's evidence by id instead
of comparing JSON blobs and hoping key order stays stable. The frontend now sends
it, and a job without one is still perfectly legal — backtesting an unsaved draft
is an ordinary thing to do.

## Three layers, each with one job

`strategy_rules.action` is what the **owner declared**. `execution_policies` is
what the **server agreed to**, written only by the arming route, with the evidence
attached. The snapshot the executor will obey lives on the intent and the position,
so a later edit cannot move a live stop. That separation is why `RuleUpdate` still
has no `action` field: the kind is not settable through the rules API at all.

And a PATCH that changes a rule's `params` now disarms it, next to the line that
already clears its pending streak for the same reason. The rule that passed the
backtest no longer exists, so its permission does not either.

## `DexTradeActionConfig`

A discriminated union on `kind`, like `RuleParams` on `agent`: a misspelled field
has to be a 422 when written, because a loose dict here produces a rule that
spends money on terms nobody validated. `ExitPlan` is nested **verbatim** — one
type for how a signal becomes a trade, so the report and the executor cannot mean
different things by a stop.

Two fields exist here only because they live on `BacktestCreate` rather than on
`ExitPlan`, and a live fire needs them: `neutral`, and `sides` — fixed at `"long"`,
since an action that claimed otherwise would be armed against evidence a pool
cannot produce. And a validator refuses a plan with no target and `max_bars > 200`:
a live position needs a bound that is not the stop, because the stop may never
arrive.

## The gate

`services/execution/preflight.py`, pure and synchronous — the caller loads the
job, this decides. Called from the arming route and **not** from the executor,
because a gate evaluated at execution time would stop trading mid-position when
history rolled past the age limit, which is the worst moment to lose the exit path.

*Identity*: same rule id, pair, timeframe, params; the same behavioural exit fields
(costs deliberately excluded — a report measured through a dearer pool is still
evidence about the same strategy); the same `neutral`; `sides == "long"`; the
current `PARITY_VERSION`; and evidence newer than 14 days. Plus a refusal when
`max_bars × timeframe` exceeds 45 days, which `ExitPlan` alone cannot catch.

*Quality*, from the unseen half only: at least 30 trades, expectancy above **the
owner's** threshold, drawdown within **the owner's** limit, and none of
`likely_overfit`, `too_few_trades` or `no_edge_detected`. The owner sets the bar
because it is their money and their patience; they cannot set it to zero, because
there is no reading of a losing unseen result that makes it evidence. `min_trades`
is not settable at all — a preference cannot make a small sample larger.

*Cost honesty*: once an account has ten closed positions, its own measured `cost_r`
must not exceed the report's by more than half again. A strategy measured at 0.05%
fees that is really paying 0.3% is not the strategy that passed — the cost work
from 2026-09-26 doing real safety work.

Every failure is returned at once. An owner fixing one at a time learns nothing
about the rest, and this is the only place that will ever tell them why their
strategy may not spend.

## `/api/execution/*`

`GET`/`PUT /account`, `POST`/`DELETE /kill`, `GET /policies`,
`POST /rules/{id}/preflight`, and `POST`/`DELETE /rules/{id}/arm`. Owner-scoped,
404 rather than 403 on a mismatch, and arming returns **409 with every reason**.
An unconfigured account reads as the defaults rather than as an error — "off, and
these are the caps you would start from" — and reports the global switch alongside,
because an account that looks armed while execution is off is the most confusing
state to debug.

Disarming is always allowed, and the kill switch can be flipped before an account
exists. Neither ever needs to wait for anything.

**What this route still lacks, and must before live mode:** a fresh signature over
the specific change. A bearer token in `localStorage` is the right ceiling for
reading and editing rules and the wrong one for authorising spend — the frontend
says so itself. It holds for now because arming requires a passing backtest and
every account is off.

Backend 617 tests (was 564), frontend 72, `next build` clean.

## Next

Slice 4 is the vault contract — Foundry, a factory, Arbitrum Sepolia — which is
where this stops being only schema.

---

# Slice 4 — the vault

`contracts/`, a Foundry project with **no submodules and no libraries**. Every
interface it needs is four lines long and lives in `src/interfaces`. A contract that
holds someone's money should be readable end to end in one sitting, and a dependency
tree is the opposite of that.

## What it is

One vault per (owner, market), deployed by the owner from a factory. It holds USDC,
it can swap into one whitelisted asset and back, and it can do nothing else.

**Changed from the design:** one asset per vault rather than a whitelist. A vault
with a portfolio needs position bookkeeping and an answer to "which balance funds
this trade"; a vault with one asset needs neither, and `simulate` holds one position
at a time too. Two markets is two vaults.

## The operator's surface, which is the whole security argument

`openPosition` and `closeByOperator`. That is all. There is no transfer, no
arbitrary approve, no setter for the router, the oracle or the asset, and **no
function anywhere that changes a stop once written** — not for us, not for the
owner. A bot cannot give a losing position a little more room.

The owner's rights are unconditional and cannot be blocked, delayed or front-run by
us: `deposit`, `withdraw` (position open or not), `setOperator`, `revokeOperator`,
`setCaps`, `closeByOwner`.

## Exits that do not depend on our uptime

`closeIfStopped`, `closeIfTargetHit`, `closeIfExpired` — **permissionless**, each
reverting unless the condition is genuinely true, each paying a flat bounty from the
vault to whoever called it. Not to us and not to the owner: paying ourselves out of
their vault for work we said we would do is a fee by another name, and the test that
pins that says so.

A contract cannot notice a price — EVM code runs only when called — so the vault
verifies and something outside pushes. Our executor normally does, within seconds;
if it is down, a stranger has a profit motive to, which is the mechanism that makes
liquidations reliable without trusting one operator.

**Oracle authorises, minimum-out protects.** `MAX_ORACLE_AGE` is 26 hours: the
Chainlink daily heartbeat plus slack. Tighter would make exits impossible in a quiet
market, which is worse than the risk it removes. And the vault publishes
`openFloor(amountIn)` and `closeFloor()` so the executor asks the vault what the
floor is rather than computing its own and disagreeing — the same move as
`trade_plan.py`, one floor rather than two.

## What the tests are about

28 offline tests, mostly **refusals**, because that is what the vault is for: the
operator cannot withdraw, cannot re-open over an existing position, cannot exceed
the notional cap or the daily count, cannot act on an expired grant, cannot place a
stop on the wrong side of the price, cannot open against a stale feed. The owner can
withdraw while a position is open. Revoking is immediate. Deposits stop at the hard
cap, and `setCaps` cannot loosen past the contract's own ceilings.

Two worth naming:

- **A stranger closes a stopped position and is paid; the operator is not.** Both
  halves matter.
- **The vault checks the fill itself even if the router does not.** Uniswap's router
  enforces the minimum we hand it, so the first version of the sandwich test was
  passing for the wrong reason — the router refused before the vault did. A mock
  that under-delivers *silently* proves the vault's own check is a guarantee rather
  than something it borrows.

`test/Fork.t.sol` is the only test that can say whether the addresses in
`src/Addresses.sol` are the contracts we believe they are — everything else runs
against mocks that agree with us by construction. It skips without
`ARBITRUM_RPC_URL`, and it must be run before any deployment.

## The risk ladder, enforced in code

`VaultFactory.TVL_CAP = 500e6`, a constant. Raising it means deploying a new
factory, so nobody — including us — can raise it on a live vault. Sepolia first,
then mainnet at five hundred dollars a vault, then an audit, then a higher cap.

## Client side

`frontend/lib/vault.ts`: the ABIs, the market list mirroring the factory's, amount
handling for USDC's six decimals and Chainlink's eight, and the **disclosure**.

That last one is load-bearing rather than decorative. The vault stores
`keccak256(disclosure text)` at deploy, so which wording an owner accepted is a fact
on-chain with a block timestamp, not a row in our database. `DISCLOSURES` is
append-only and the hash of v1 is pinned by a test: a failure there means someone
edited an accepted version instead of adding one, and every vault that accepted v1
would now disagree with the site about what its owner agreed to.

28 contract tests (1 skipped), frontend 82, backend unchanged at 618.

## Not done in this slice

The vault UI — deploy, fund, set the grant, revoke, withdraw. The client library is
here and tested; the panel lands with slice 5, because a vault with no executor has
nothing to do yet.

---

# Slice 5 — the executor

First slice where anything runs. It still cannot spend: `execution_settings.enabled`
is `FALSE`, every account is `off`, `EXECUTION_ENABLED` defaults to false, and the
only registered venue is the shadow wrapper — an account in live mode gets a refusal
rather than a silent downgrade, because pretending to trade is worse than admitting
we cannot.

## Where it runs, and why not anywhere else

A sixth container. Not the API: the alert sweep lives there and `fire()` awaits the
action inline, so one slow RPC would delay every other wallet's alerts — and with
`coalesce=True` a multi-minute stall does not arrive late, it silently drops the bars
that closed during it, because `set_pending` has already moved `last_candle_time` and
no dedup key is ever minted. Those fires are gone. The API also restarts on every
deploy.

Not the backtest worker either: `cpu_shares: 256`, `mem_limit: 512m`, and a replay
that saturates a core for up to an hour. An exit cannot queue behind that, and being
OOM-killed mid-trade by our own replay would be the worst coupling in the system. The
executor gets `cpu_shares: 1024` and `mem_limit: 256m` — latency-sensitive and
near-idle, the opposite of a replay — and a 90-second heartbeat window rather than
180, because a dead executor holding open positions must be noticed inside a bar.

## The pipeline, and where each guarantee lives

| Step | Where | What makes it safe |
|---|---|---|
| fire → queued | `actions/dex_trade.py`, in the sweep | no network, no new row: it returns `queued` and `fire()` writes that into the event it is already committing |
| queued → intent | `execution/promote.py` | `UNIQUE (event_id)` — safe to re-run, safe to run twice at once, safe to interrupt |
| intent → claimed | `CLAIM_SQL` | every cap in one statement, `FOR UPDATE OF c SKIP LOCKED`, exits ahead of entries |
| claimed → sent | `execution/runner.py` | the order row, with its `client_order_id`, is inserted **before** the venue call |
| sent → booked | same | `UNIQUE (venue, venue_fill_id)`, and one live position per rule |

`models/database.py` has no transaction spanning two statements, and this design does
not need one: there is never a moment where a dedup key has been burnt but no work
exists, because the event row *is* the queue until the executor promotes it.

## The distinction the whole thing rests on

`VenueRejected` is a promise about state — it definitely did not happen, so a retry
is safe. `VenueUnknown` is an admission — we do not know, so it may **never** be
retried; it becomes `needs_reconcile` and waits to be told what is true. An adapter
that cannot tell them apart must raise the second. `tests/fake_venue.py` has
`landed_but_lost_the_response()` for exactly the case where the swap goes through and
the answer does not, and the test asserts one order row, one venue position, nothing
in our books — the state reconciliation exists to resolve.

## What the vault removed from this design

The plan had a "place the trigger orders after the entry fills" step, and called the
window between an open position and a protected one the highest-priority repair. With
a vault there is no such window: the stop, the target and the deadline are written in
the same transaction as the swap. `triggers_placed` is true by construction, and the
monitor's job shrinks to being *first* rather than being the only one who can act.

## The monitor

`decide()` is pure, so the table is tested without a clock or a database. Order: a
halt beats everything including a printing target; then the deadline, from the clock
alone, so a data outage cannot leave a position unmanaged; then the stop against the
**live price**; then closed bars through `trade_plan.bar_exit`.

The stop on the live price is a deliberate departure from the report, which models it
filling *at* the stop when a bar's low reaches it. Waiting for the close would leave
the position exposed for the rest of the bar. Capital protection wins, the trigger is
recorded on the position (`quote` or `bar`), and the target stays close-based —
being slow to take profit costs opportunity, firing a target on a wick costs parity.

## Reconciliation, which is deliberately unlike the backtest worker

`requeue_running()` blindly resets every running job at boot, which is safe because a
replay has no side effects. An intent's side effect is a trade. So the venue is the
authority, in-doubt writes are matched against it, and **anything unexplained halts
the account and never flattens** — a reconciliation bug that flattened would turn a
display error into a realised loss. A position with no fill to read is abandoned
rather than given invented numbers.

Exits keep running while an account is halted. A halt is about not opening.

## Found by the tests

The action mapped a signal's direction *with* the long-only filter, so a bearish
signal became `None` and `exit_on_opposite` never saw it — the position would have
been held through the exact signal the owner asked to exit on. The same mistake slice
2 avoided in `simulate`, made again two files later. The mapping is now unfiltered and
the side is refused separately, as it is there.

## Shadow mode

A wrapper, not a branch: reads go to the market so sizing and triggers see live
prices, and the same code path runs that live runs. Costs come from the plan, so a
shadow run reproduces the report's cost model exactly — and the gap that shows up in
live is then the gap between the model and the chain, which is what the preflight's
cost check is looking for.

Backend 704 tests (was 618). Frontend and contracts unchanged.

## Next

The vault UI — deploy, fund, grant, revoke, withdraw — and the vault venue adapter,
which is the last thing between shadow and live. Then a week in shadow before either.

---

# Slice 6a — the live adapter

The last thing between shadow and live. Two decisions were taken with the owner: a
signer *interface* with an env-var key for testnet and KMS before mainnet, and the
**public** Arbitrum RPC.

## No new dependencies

`eth_abi`, `eth_account`, `eth_utils` and `httpx` are already here — the first three as
dependencies of the sign-in path, `httpx` as the candle service's client. So the
adapter is a hand-written JSON-RPC client and a hand-written encoder, and `web3.py`
never arrives.

That is not only about the 256 MB the executor is capped at. A library whose job is to
hide the encoding would also hide the part that matters: this module and
`TradingVault.sol` have to agree exactly. `tests/test_execution_abi.py` parses the
Solidity and compares every signature, every error selector, the `Position` struct's
field count, and the two token addresses `markets.py` duplicates from
`Addresses.sol`. A renamed function or a re-typed argument fails a test rather than
reverting in production.

## What the public RPC forced, and why it is better

A public node rate-limits and occasionally drops requests, and here a dropped request
means `VenueUnknown`, which parks an intent until reconciliation. Two things make it
workable:

**Reads retry; sends never.** `eth_call`, a nonce and a balance are idempotent, so a
rate limit costs latency. `eth_sendRawTransaction` is sent exactly once.

**We sign locally, so the transaction hash exists before the broadcast does.** A send
that times out is therefore not a dead end — the hash can be asked about until the
answer is definite. Without that, every timeout on a rate-limited node would strand a
position; with it, most "cannot tell" becomes "here is what happened".

`"already known"` and `"nonce too low"` are treated as *already broadcast* rather than
as failures, because building a second transaction in response to either is precisely
how an account spends twice.

## The five steps, in this order

1. **ask the vault for its floor** (`openFloor`) — our minimum-out cannot be looser
   than the one the contract enforces, and cannot be tighter either, which would
   refuse fills the owner already agreed to;
2. **simulate** with `eth_estimateGas` — a revert here is a definite refusal, learned
   before anything is signed, which is how most failures become `VenueRejected`;
3. **sign**, which yields the hash;
4. **broadcast once**;
5. **read back** what happened: the qty from the vault's own position, and on the way
   out the proceeds from the change in its stablecoin balance.

Step 5 matters: the fill price is a fact about the pool, and inferring it from a quote
would put a number in the audit trail that nothing on chain agrees with. The pool fee
is already inside that price, so `fee_usd` is zero — charging it again would
double-count what the report models once. Gas is priced through the ETH/USD feed;
without a feed it reads as zero, and since an under-reported cost flatters a strategy
the feed is configured by default rather than optional.

## Where the vault address comes from

`vaultOf(owner, asset)` on the factory, cached. Not stored on the policy: the factory
is the one place that knows which contract belongs to an owner, and a stale address in
our database would be a transaction sent to the wrong contract. An owner with no vault
is a refusal, not a zero address.

## The signer

One protocol, one implementation. `LocalSigner` reads a key from the environment,
never logs it, and will not put it in an error. A KMS signer implements the same
protocol and is what should sign against mainnet.

What limits the damage either way is the vault, not the signer: the key can swap
inside a contract the owner controls, within caps they set, and has no path to
withdraw. No key at all is a normal state — shadow needs none, and an executor without
one idles rather than crash-looping on a machine that was only ever meant to run
shadow.

## Still off

`mode: live` requires a signer, a factory address and a deployed vault, and the
absence of any of them is a refusal rather than a downgrade to shadow. The global
switch and every account are unchanged: off.

Backend 762 tests, up from 708.

## What is left before a live trade

1. Deploy the factory to Arbitrum Sepolia and run `test/Fork.t.sol` against it — the
   only test that can say the addresses are the contracts we believe they are.
2. An executor key, and `EXECUTOR_ADDRESS` published so the panel can offer a grant.
3. A week in shadow, reading entry drift and exit slippage out of
   `GET /api/execution/positions/{id}`.
4. The legal rewrite and the Play re-declaration, which are slice 6's other half and
   are not optional.
5. A KMS signer before mainnet.

---

# Slice 6b — the copy

Not decoration. The terms incorporate the risk page by reference, the Play
declaration repeats it, and the disclosure a vault owner signs is hashed into their
contract forever. So this is the slice where the product stops describing something
it no longer is.

## What was false, and is now gone

`"We do not execute trades. The app has no order placement of any kind."` ·
`"Alerts only: nothing here places a trade."` · `"it places no trades, holds no
funds"` · `"we cannot move anything, and signing in authorises no transaction"` ·
`"A free, informational tool"`.

## What replaced it, and why in that order

The risk page leads with the thing people most need to believe and can check:
**your money stays in your contract**, and the permission we hold cannot withdraw
from it — *there is no function in that contract by which we could, whatever we
wanted or were asked to do*. That is a claim about code, not about intentions, which
is the only kind worth making.

Then, in the order someone would be hurt by not knowing:

| | |
|---|---|
| Your stop does not depend on us | it is in the contract, anyone can trigger it, and the contract pays them for it |
| A stop is not a fill price | the contract permits an exit at the level; the pool decides what you get |
| Three prices disagree | signals from a centralised exchange, stops from Chainlink, fills from a pool — and we show the gap in bps |
| Costs can exceed the edge | 0.03R a trade on 1d, over 2R on 5m; the gate refuses what does not clear its own costs |
| A backtest is required and still not a forecast | it stops the obvious mistakes and nothing more |
| Start in shadow | a week costs nothing and is the most expensive thing to skip |
| The contract is unaudited | with a cap we cannot raise either |
| Entries depend on us, exits do not | read twice before relying on either |

Two sentences were kept deliberately rather than softened: *"We do not choose what
to trade"* and *"not investment advice"*. Execution does not make us an adviser, and
the copy should not drift toward implying it might.

## The Play declaration

The one part that is not ours to phrase freely, and the note now says the thing that
is easy to miss: the TWA is a wrapper around `app.vibetrading.club`, so **the Android
app gains execution the moment the web app does** — no new build, no store review.
The declaration therefore has to change *before the feature is enabled for anyone*,
not before the next release. Enabling it with the old answer standing is a false
declaration. What the answer needs to become is written out; whether Play also wants
its crypto-exchange or financial-services declarations is left as a policy reading to
do at the time rather than guessed at here.

## The test

`frontend/tests/legal.test.ts` asserts in both directions: the claims that stopped
being true are gone from all four pages, and the ones that are still true and
load-bearing are still there in the words the contract enforces.

Two cross-checks beyond that, and they are the interesting ones:

- **the site may not contradict the text a vault owner signed.** The disclosure's
  hash lives in their contract forever, so if the risk page said something looser
  than what they accepted, the accepted text would be the one that counted and we
  would be the ones out of step.
- **the architecture page counts what is actually deployed.** It parses
  `docker-compose.prod.yml` and compares the service count to the number word on the
  page, which is how "five containers" stopped being true without anyone noticing
  the first time.

893 tests across the three suites, counted rather than estimated — the page said 425
until today.

## Still not done before a live trade

Deploying the factory to Sepolia and running the fork test; an executor key and its
published address; a week in shadow; the Play answer actually changed in the console;
a KMS signer before mainnet.

---

# Slice 7 — deployed, and a way to arm it

## Deployed

The VM went from `21bdac1` to `801e97e`: six containers now, the executor among them.
Verified rather than assumed:

| | |
|---|---|
| `/api/execution/account` | **401** where it was 404 the hour before — the routes exist |
| Migration 006 | eight tables created |
| `execution_settings.enabled` | `false` — it ships off, as designed |
| Executor | healthy, log reads *"EXECUTION_ENABLED is not set; idling"* |
| Memory | **61 MiB of its 256 MiB cap**, 801 MiB still free on the machine |

That last row settles something I raised in the design and got wrong: I flagged that
the executor's numpy import might force an `e2-medium`. Measured, it does not come
close.

The deploy also closed a papercut I had created myself. The frontend deploys from
`main` automatically and the backend does not, so the Vault button had been live for
several commits against a backend with no `/api/execution` at all — a 404 the moment
anyone clicked it.

## A way to arm a rule

Until now arming was API-only, so the feature was unreachable from the product. The
Armed tab gains a **Trade** button per rule, which becomes **Trading** once armed.

The shape of that sheet is an argument, not a layout. **You cannot type an exit plan
in it.** The plan is read out of the backtest you pick, because the point of the gate
is that what trades is what was measured, and a field that let you arm a different
stop than the report tested would quietly undo the whole thing. What you do set is the
bar the report must clear and how much money a trade may use.

Three refusals it makes before the server has to:

- **A rule on a pair with no pool and no feed cannot be armed at all.** Seven of the
  nine pairs the app charts are in that position, and the sheet says so in those
  words rather than letting the server refuse it later with less context.
- **Only this rule's finished backtests are offered.** A report about something else
  is not evidence, and the gate would reject it with a worse message.
- **Arm stays disabled until the check passes**, and a refusal renders *every* reason
  the gate gave, in a list. That is the only screen that will ever explain why a
  strategy may not spend.

The copy under *Arm rule* also changed: "Alerts only; nothing here places a trade" was
true of that button and is no longer true of the tab it sits in.

Backend 762, frontend 105, contracts 28.

## Still not done before a live trade

The factory on Sepolia with the fork test green; an executor key and its published
address; a week in shadow; the Play answer actually changed in the console; a KMS
signer before mainnet.
