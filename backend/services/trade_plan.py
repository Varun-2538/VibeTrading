"""
The pure half of a trade: where it enters, where it gets out, and how big.

The backtester reads a whole candle array at once and a live executor reads one
bar at a time, but what the two decide has to be identical, so what they decide
lives here - no I/O, no clock, no state. This is the same split that produced
services/rule_decision.py, which is why a replay fires on exactly the decisions
the live engine makes.

`bar_exit` is the load-bearing one. backtest/trades.py loops over it and a live
monitor calls it once per newly closed bar, so first-hit-wins, worse-case-inside-
a-bar and gap-fills-at-the-open exist in one place and cannot drift apart.

PARITY_VERSION is stamped on every backtest report and on every armed execution
policy. A rule armed under an older version is refused rather than migrated: a
silent change to where a stop goes is exactly the drift this module exists to
make impossible.
"""
from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence, Tuple

from analysis.patterns import atr
from models.backtest_schemas import ExitPlan

PARITY_VERSION = 1

ATR_BARS = 15  # ATR(14) needs 15 bars

# What the trade does. A live executor reads these and obeys them; they are the
# strategy, and there is one copy of each.
BEHAVIOURAL_FIELDS: Tuple[str, ...] = (
    "stop_atr", "stop_pct", "target_r", "target_pct",
    "max_bars", "exit_on_opposite", "risk_pct",
)

# The cost *model*. Live does not read these for behaviour - it pays what the
# pool and the chain charge and measures it afterwards. They are kept on an armed
# plan only so a report's assumed costs can be compared against what an account
# has really been paying.
COST_FIELDS: Tuple[str, ...] = ("fee_pct", "slippage_pct", "gas_usd", "trade_usd")


# Which directions a venue can take. A Uniswap pool has no short: a position is
# the asset or it is stablecoins, so a report full of short trades is not evidence
# for spot execution.
SIDES: Tuple[str, ...] = ("both", "long", "short")


def signed_direction(direction: str, neutral: str, sides: str = "both") -> Optional[int]:
    """
    A signal's direction as +1 long, -1 short, or None for "do not trade it".

    Two separate questions, deliberately: `neutral` is how a signal with no
    direction of its own is read (a doji, an inside bar, a volume spike), and
    `sides` is which directions this venue can take at all. Both belong here
    rather than on ExitPlan, because both decide whether a trade happens rather
    than how it ends - and a live executor has to answer them the same way.
    """
    if direction == "bullish":
        d: Optional[int] = 1
    elif direction == "bearish":
        d = -1
    else:
        d = {"long": 1, "short": -1}.get(neutral)
    return d if d is not None and tradable(d, sides) else None


def tradable(d: int, sides: str) -> bool:
    """Whether this venue can take that direction at all."""
    return not ((sides == "long" and d == -1) or (sides == "short" and d == 1))


@dataclass(frozen=True)
class Bracket:
    """Everything a trade needs before its first bar: prices, and how big."""

    entry: float
    dist: float
    stop: float
    target: Optional[float]
    # Fraction of equity, already clamped. See notional_fraction: the clamp is
    # why a wide stop takes less than the risk that was asked for, and live has
    # to inherit that rather than re-derive it.
    notional: float


def entry_price(reference_open: float, d: int, slippage_pct: float) -> float:
    """The fill, priced against the trade: a buy pays up, a sell sells down."""
    return reference_open * (1 + d * slippage_pct / 100)


def exit_price(reference_exit: float, d: int, slippage_pct: float) -> float:
    return reference_exit * (1 - d * slippage_pct / 100)


def stop_distance(
    plan: ExitPlan, candles: Sequence[Dict[str, Any]], signal_index: int, entry: float
) -> float:
    """
    How far the stop sits from the entry, in price.

    A percent stop is a share of the entry; an ATR stop is measured over the
    fifteen bars ending at the signal bar, so it never sees a bar the signal
    could not have seen.
    """
    if plan.stop_pct is not None:
        return entry * plan.stop_pct / 100
    end = signal_index + 1
    unit = atr(candles[end - ATR_BARS: end]) if end >= ATR_BARS else 0.0
    return (plan.stop_atr or 0.0) * unit


def target_price(plan: ExitPlan, entry: float, dist: float, d: int) -> Optional[float]:
    if plan.target_pct is not None:
        return entry + d * entry * plan.target_pct / 100
    if plan.target_r is not None:
        return entry + d * plan.target_r * dist
    return None


def notional_fraction(risk_pct: float, dist: float, entry: float) -> float:
    """
    Fraction of equity to hold so that the stop costs `risk_pct` of it.

    Capped at 1.0 - no leverage - which quietly means a stop wider than
    `risk_pct` of price risks less than was asked for, not more. Live must use
    this number rather than its own arithmetic, or it takes more risk than the
    report measured.
    """
    return min(1.0, (risk_pct / 100) / (dist / entry))


def bracket(
    plan: ExitPlan,
    candles: Sequence[Dict[str, Any]],
    signal_index: int,
    reference_open: float,
    d: int,
) -> Optional[Bracket]:
    """
    None when there is no room to trade: an ATR of zero, a flat series, a stop
    that would sit on the entry. The backtester counts that as skipped_no_room
    and a live executor must refuse it for the same reason.
    """
    entry = entry_price(reference_open, d, plan.slippage_pct)
    dist = stop_distance(plan, candles, signal_index, entry)
    if dist <= 0:
        return None
    return Bracket(
        entry=entry,
        dist=dist,
        stop=entry - d * dist,
        target=target_price(plan, entry, dist, d),
        notional=notional_fraction(plan.risk_pct, dist, entry),
    )


def bar_exit(
    open_: float,
    high: float,
    low: float,
    d: int,
    stop: float,
    target: Optional[float],
    *,
    first_bar: bool,
) -> Optional[Tuple[float, str]]:
    """
    What this one bar does to an open position: (fill price, reason), or None.

    Three rules, and every one of them errs against the strategy:

    - A bar that opens beyond the stop fills at that open, not at the stop. A
      gap is not a level you get to trade at. The same honesty runs the other
      way, so a bar opening beyond the target fills at that better open.
    - Where a bar's range cannot say which came first, the stop wins: a bar
      touching both is a loss.
    - On the entry bar there is no gap check, because the position was opened at
      that open - it cannot also be a gap through it.

    Scalars rather than a candle dict on purpose: a grid search calls this
    millions of times and building a dict per bar is the difference between
    seconds and minutes.
    """
    if not first_bar:
        if (d == 1 and open_ <= stop) or (d == -1 and open_ >= stop):
            return open_, "stop"
        if target is not None and ((d == 1 and open_ >= target) or (d == -1 and open_ <= target)):
            return open_, "target"
    if (d == 1 and low <= stop) or (d == -1 and high >= stop):
        return stop, "stop"
    if target is not None and ((d == 1 and high >= target) or (d == -1 and low <= target)):
        return target, "target"
    return None


def time_exit_bar_index(entry_index: int, max_bars: int) -> int:
    """
    The bar whose open closes a trade that has run out of bars.

    Held `max_bars` bars from the entry bar inclusive, then out at the next
    open. A live executor stores the *time* of this bar instead of counting, so
    its time exit needs no market data at all - which is what makes it the exit
    that still works when candles are unavailable.
    """
    return entry_index + max_bars


def trade_return(entry: float, fill: float, d: int, swap_cost_pct: float) -> float:
    """
    Return on the capital deployed, after the fees both swaps pay.

    The exit side's fee is charged on what the exit is worth, not on what the
    entry was, which is the `fill / entry` term.
    """
    swap = swap_cost_pct / 100
    return d * (fill - entry) / entry - swap * (1 + fill / entry)


def frictionless_return(reference_open: float, reference_exit: float, d: int) -> float:
    """The same trade paying nothing: in and out at the untouched prices."""
    return d * (reference_exit - reference_open) / reference_open


def in_r(value: float, entry: float, dist: float) -> float:
    """A return expressed in units of the risk taken to earn it."""
    return value * entry / dist


def notional_usd(fraction: float, equity_usd: float, caps: Sequence[float]) -> float:
    """
    What `fraction` of equity is worth in dollars, under every cap that applies.

    Caps are a sequence and the smallest wins, because a rule's ceiling and an
    account's ceiling are both real and neither may be the one that is applied
    by accident.
    """
    wanted = max(0.0, fraction) * max(0.0, equity_usd)
    return min([wanted, *[c for c in caps if c is not None]]) if caps else wanted
