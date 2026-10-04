# Backtest costs, the way a DEX charges them

**Date:** 2026-09-26 · ships on `main` with the backtester already deployed.

## Why

Every strategy the backtester ran came back at a loss, and the arithmetic said
why: on a 1h major, a 1.5-ATR stop is about 0.6% of price, so a round trip of
0.24% was eating roughly 0.3R of every trade before the signal had done
anything. That number was modelled on a centralised exchange's taker fee.

The user trades on-chain, in Uniswap-style pools, where the cost is not a taker
fee but **the pool's fee tier, charged on each swap** — 0.01% for stable pairs,
0.05% and 0.1% for majors, 0.3% for most volatile pairs, 1% for thin ones — plus
**gas per swap**, which is a cost in dollars and therefore a different share of
every position size.

Two things follow: the cost model has to be a pool, and the report has to say
what the costs took. A single net number cannot distinguish a strategy with no
edge from one whose edge went to the pool, and those two call for different
answers — the first is abandoned, the second is traded on a wider stop or a
slower timeframe, where the same round trip is a smaller share of risk.

## Decisions

| Question | Decision |
|---|---|
| Fee shape | `ExitPlan.fee_pct` stays the field and keeps meaning *per swap*, because a pool tier is exactly that. Kept the name so requests already in the database still parse. |
| Tiers | `POOL_FEE_TIERS = (0.01, 0.05, 0.1, 0.3, 1.0)`, picked in the panel rather than typed, since the tier belongs to the pool and not to the trade. |
| Default | 0.05%, the majors' tier — the pairs this platform has candles for. Was 0.1%. |
| Gas | `gas_usd` per swap and `trade_usd` for the position, converted to a percent by `gas_pct`. Default `gas_usd = 0`: we cannot know the chain, and a guessed default would quietly decide whether strategies pass. |
| Price impact | `slippage_pct` unchanged in meaning, relabelled "price impact" in the panel, which is what it is on-chain. |
| Where the cost shows | Per trade in R (`Trade.cost_r`), averaged per period (`cost_r`), with expectancy reported twice: `gross_expectancy_r` before friction, `expectancy_r` after. |
| Gas and position sizing | Priced as a percent of the position, so the risk-sized `notional` scales it. A fixed dollar cost does not really scale; the error is second order and in the strategy's favour on small positions, which is worth knowing and not worth modelling further yet. |

## How the cost is measured

Not by adding up the fees charged — by difference. `simulate` prices the same
trade twice: once as filled, once frictionless, in and out at the untouched bar
prices. The gap is `cost`, and `cost_r` is that gap over the stop distance.
Every friction therefore lands in one number by construction, including the
price impact that is baked into the fill prices rather than charged separately.

`gross_r = r + cost_r` holds exactly. It does not land exactly on the
frictionless trade's R, because the stop and target are placed off the *slipped*
entry, so paying impact moves them a hair further out — about 1% of one R on a
2% stop, pinned by a test so the decomposition cannot silently drift.

## What shipped

Backend: `models/backtest_schemas.py` (tiers, `gas_usd`, `trade_usd`, `gas_pct`,
`swap_cost_pct`), `backtest/trades.py` (`swap` cost per side, `cost_r`,
`gross_r`), `backtest/metrics.py` (`gross_expectancy_r`, `cost_r`, `cost_r` per
trade row). Four new tests in `tests/test_backtest_trades.py`, the defaults
pinned in `tests/test_backtest_schemas.py`. 486 pass.

Frontend: `lib/backtests.ts` (`POOL_TIERS`, `gasPct`, `roundTripPct`,
`costNote`), `components/backtest-sheet.tsx` (tier picker, gas and position
fields, a live round-trip line, "Before costs" and "Costs took" rows). Two new
tests. 70 pass, `next build` clean.

The new report fields are optional on the client: reports that finished before
this model exist in the database and must keep rendering.

Legal: the risk page now states how costs are charged and that the three
numbers, not the net one, are what to read.

## Not done

- Fixed gas modelled as fixed, against the risk-sized position.
- A per-chain gas preset. The field is there; a table of chains is guesswork
  until the user says which one they trade.
- Pool depth. Price impact is a flat percent, not a function of the pool's
  liquidity and the trade's size against it.

## Measured, against prod candles (2026-09-26)

`atr` over the last 15 closed BTCUSDT bars from the live API, a 1.5-ATR stop,
0.02% impact, no gas. The cell is what one round trip costs, in R:

| tf | ATR% | stop% | 0.01% | 0.05% | 0.1% | 0.3% | 1% |
|---|---|---|---|---|---|---|---|
| 5m | 0.037% | 0.055% | 1.09R | 2.53R | 4.34R | 11.58R | 36.92R |
| 15m | 0.104% | 0.156% | 0.39R | 0.90R | 1.54R | 4.11R | 13.10R |
| 1h | 0.248% | 0.371% | 0.16R | 0.38R | 0.65R | 1.72R | 5.49R |
| 1d | 2.912% | 4.368% | 0.01R | 0.03R | 0.05R | 0.15R | 0.47R |

And gas, on the 0.05% pool with that 1h stop: $0.30 a swap on a $1,000 position
is 0.54R a trade; $2 a swap is 1.45R; the same $2 on a $5,000 position is 0.59R;
$15 — mainnet at a bad hour — is 8.45R.

Two things this settles. **Intraday on-chain is not a cost problem, it is an
impossibility**: nothing pays 2.5R a trade on 5m, whatever the signal. The
platform's own scale says a 1d stop is 80× a 5m stop, and costs scale inversely.
**Gas is the dominant term for small positions**, which is why it had to be a
field and not a constant.

This also killed the panel's first footnote, which converted the round trip into
R with a hardcoded "about 0.6% of price" for a 1.5-ATR hourly stop. The measured
figure that day was 0.37%, so the note understated costs by a third in calm
markets and would overstate them in a violent one. It now runs the arithmetic the
other way — the stop distance a given round trip needs to stay under 0.2R of
cost — which needs no view on volatility at all.
