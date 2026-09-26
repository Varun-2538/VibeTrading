# Autonomous execution: rules that trade, not only alert

**Date:** 2026-09-26 · design approved before slice 0.

## Why

A rule can only raise an alert. `services/actions/__init__.py` has named the seam
since phase one — *"a DEX executor registers as `dex_trade` and the rule's `action`
JSONB carries its configuration"* — and the column has existed, unused, since
`001_strategy_rules.sql`. The owner wants the bot run for them: they build the
strategy, we watch, and the trade happens with the browser closed.

## The inversion that makes it defensible

**Entries depend on our uptime; exits do not.** A missed entry costs an
opportunity, a missed exit costs capital. So every exit is enforced on-chain and
callable by anyone, and our executor is merely the fastest caller. The risk page
currently has to say *"Do not use alerts as risk management… delivery is best
effort"*; this design is what lets a stop stop being best effort.

## Decisions

| Question | Decision |
|---|---|
| Who executes | We do, for the user, after explicit consent. |
| Venue | Uniswap spot on Arbitrum One — the chain the session message already pins. |
| Custody | **None.** A per-user `TradingVault` the user deploys and owns. |
| Our permission | An operator role that can only swap through a hardcoded router, within caps, and can never withdraw. |
| Stops | Written into the vault at open, immutable afterwards **by anyone including us**, verified against a Chainlink feed. |
| Who pushes the exit | Our executor normally; anyone, for a bounty, when we are down. |
| Which rules may execute | A backtest is mandatory. The user sets the pass threshold. |
| x402 | Not an execution mechanism (it is an HTTP-402 payment protocol). Deferred, for charging the fee. |

### Why a purpose-built vault rather than ERC-4337 + a session key

The policy we need is unusually narrow: one router, three tokens, a per-trade cap,
a daily cap, an expiry. Narrow policy in immutable code is easier to prove correct
than general policy in a module's configuration, and it needs no bundler or
paymaster on a single small VM. The cost is that the contract becomes ours to get
right, which is why the ladder is Sepolia → a `tvlCap` of $500 hardcoded in the
contract → audit → raise. The cap lives in the contract so we cannot raise it
either.

### What a contract can and cannot do

A contract cannot notice anything. EVM code runs only when a transaction calls it:
no timers, no loops, no price watching. So the vault *stores and verifies* the
stop, target and deadline, and something else *notices*. Making
`closeIfStopped` / `closeIfTargetHit` / `closeIfExpired` permissionless with a
small bounty gives that noticing a profit motive — the mechanism that makes
lending liquidations reliable without trusting any single operator.

Oracle authorises, `minOut` protects: the feed decides whether an exit is allowed,
and the minimum-out we pass stops a permissionless caller routing the swap through
a manipulated pool and keeping the difference.

## Three prices, and long-only

Signals are computed on **Binance** candles, exits are authorised by a
**Chainlink** feed, fills happen at the **Uniswap pool**. They differ; the drift is
measured in bps on every fill and stated on the risk page rather than hidden.

And spot has no short: a position is the asset or it is USDC. `backtest/trades.py`
simulates shorts, so a report containing short trades is not evidence for this
venue. A long-only backtest mode is a prerequisite, not a nicety.

## Server shape

Execution runs in its own container, not in the 60s alert sweep: a slow RPC there
would delay every other wallet's alerts, `coalesce=True` turns a stall into
silently dropped bars, and the API restarts on every deploy. It does not run in
the backtester either — that container is deliberately CPU-starved and memory
capped for hour-long replays, and an exit cannot queue behind one.

The action therefore does no I/O. It computes the plan and returns
`ActionResult("queued", …)`, which `fire()` already persists; the executor turns
queued events into intents on its own clock, made idempotent by a unique index on
`event_id`. Exactly-once comes from uniqueness constraints — one live position per
rule, one intent per fire, one order per `client_order_id` — never from a Python
check, because a read-then-act check is a race the moment two processes exist.

Parity with the backtester is structural: the pure exit and sizing maths lives in
`services/trade_plan.py` and both callers use it, stamped with a `PARITY_VERSION`
that must match for a rule to be armed.

## What has to change outside the code

The legal text is not marketing: the terms incorporate the risk page by reference,
and the Play Console declaration *"executes no trades… connects to no bank or
card"* is regulator-facing and must be re-declared. The sentences that become
false are enumerated in the slice plans. Consent is recorded as
`keccak256(disclosure version)` in the vault at deploy — a timestamped on-chain
record of which text was agreed to, rather than a database row.

The session token is not authorisation to spend. `frontend/lib/session.ts` already
says so: *"It must not be the storage choice once a rule can spend money."* Every
mutating execution route needs a fresh EIP-4361 signature over that specific
change, through the machinery sign-in already uses.

## Out of scope

Perps, leverage, shorting, multi-venue routing, portfolio-level allocation,
copy-trading, and anything that takes custody of funds.
