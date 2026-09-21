# Indicator Triggers, Slice A: eight new armable triggers — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** EMA crosses, MACD crosses, stochastic crosses, Bollinger band crosses and squeezes, VWAP crosses, volume spikes and ATR expansion become sequence-rule steps — armable alone or chained, parseable from chat, and backtestable — alongside the RSI step that exists today.

**Architecture:** `analysis/indicators.py` grows pure numpy series functions (stochastic, Bollinger, session VWAP, volume ratio, ATR series, series-vs-series crossings). Each trigger is a new **step type** in the sequence-rule discriminated union, with its own mask builder in `analysis/sequence.py`, its own sentence in `describe_steps`, and a direction rule in `services/rule_decision.py`. Because steps are data, the rules engine, the backtest replay and the chat draft path all pick them up with no further changes.

**Tech Stack:** Python 3.11, numpy, Pydantic v2, pytest.

**Spec:** the design agreed in conversation on 2026-09-22 (this file is the record; there is no separate spec doc). Slice B, planned separately, adds the Strategy panel builder, the chat assistant's view of the new indicators, and its Alert button for them.

## Global Constraints

- **Existing armed rules must keep working.** Rules already in the production database store steps as `{"type": "candle" | "indicator" | "structure", ...}`; `IndicatorStep` (RSI) keeps its exact shape and defaults. New triggers are new `type` values, never changes to old ones.
- **No look-ahead, ever.** Every series function may use only bars up to and including the bar it labels, and warm-up bars are `NaN` (never zero-filled). A mask is `False` wherever an input is `NaN`.
- Indicator defaults: EMA 20/50 · MACD 12/26/9 · stochastic 14/3/3 · Bollinger 20 and 2σ (squeeze lookback 120) · VWAP anchored to the UTC day · volume spike 2× over 20 bars · ATR expansion 2× over ATR(14).
- **Direction** of a sequence signal comes from its last step: a cross *above* reads bullish, *below* bearish; a Bollinger squeeze, a volume spike and an ATR expansion have no direction of their own, so they take the **colour of the bar** they fire on (close > open bullish, close < open bearish, equal neutral).
- **A day-anchored VWAP rule on the 1d timeframe is refused** at create time, naming the week anchor as the alternative: a session VWAP over one candle is that candle's typical price.
- `SequenceRuleParams.lookback` must cover the longest warm-up among its steps plus the step window; the existing check is extended rather than replaced.
- Commits end with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`; scan staged diffs for `csk-`, `gsk_`, `JWT_SECRET=` before committing.

**Running tests.** Backend from `backend/`, Python 3.11 env: `python -m pytest -q` (baseline **425**). Frontend from `frontend/`: `npx vitest run` (baseline **62**), `npx tsc --noEmit -p .` (only the pre-existing `tests/sw.test.ts` error).

## File Structure

| File | Responsibility |
|---|---|
| Modify `backend/analysis/indicators.py` | `sma`, `stochastic`, `bollinger`, `vwap`, `volume_ratio`, `true_range`, `atr_series`, `crosses_series`; `INDICATORS` grows. |
| Modify `backend/models/rule_schemas.py` | Seven new step models, the union, warm-up accounting, the VWAP/1d refusal. |
| Modify `backend/analysis/sequence.py` | `step_mask` dispatch and `describe_steps` wording for each new step. |
| Modify `backend/services/rule_decision.py` | Direction per step type, including bar colour. |
| Modify `backend/agents/rule_parser.py` | Prompt vocabulary so chat can draft them. |
| Modify `backend/tests/test_indicators.py`, `test_sequence.py`; create `backend/tests/test_rule_steps.py` | Tests. |
| Modify `frontend/lib/rules.ts` | Step types mirrored so chat drafts type-check. |

---

### Task 1: Indicator series

**Files:** Modify `backend/analysis/indicators.py`; Test `backend/tests/test_indicators.py` (append)

**Interfaces:**
- Produces, all returning `np.ndarray` the same length as their input with `NaN` warm-up:
  - `sma(values, period) -> np.ndarray`
  - `stochastic(highs, lows, closes, k_period=14, k_smooth=3, d_period=3) -> Tuple[np.ndarray, np.ndarray]` — smoothed %K and %D
  - `bollinger(closes, period=20, std=2.0) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]` — middle, upper, lower, bandwidth (`(upper - lower) / middle`)
  - `vwap(highs, lows, closes, volumes, times, anchor="day") -> np.ndarray` — cumulative typical-price VWAP, reset at each UTC day or week boundary
  - `volume_ratio(volumes, period=20) -> np.ndarray` — volume ÷ mean of the **previous** `period` volumes
  - `true_range(highs, lows, closes) -> np.ndarray`
  - `atr_series(highs, lows, closes, period=14) -> np.ndarray` — mean true range of the previous `period` bars, excluding the current one
  - `crosses_series(a, b, direction) -> np.ndarray[bool]` — `a` crossed `b` on this bar
  - `INDICATORS = ("rsi", "ema", "macd", "stochastic", "bollinger", "vwap", "volume", "atr")`
- Consumes: nothing new.

- [ ] **Step 1: Write the failing tests** (append to `backend/tests/test_indicators.py`)

```python
import numpy as np

from analysis import indicators as ind

DAY = 86_400_000
HOUR = 3_600_000


def test_sma_warms_up_with_nan():
    out = ind.sma(np.array([1.0, 2, 3, 4]), 3)
    assert np.isnan(out[:2]).all()
    assert out[2] == 2.0 and out[3] == 3.0


def test_stochastic_reads_position_in_the_range():
    # Closes climb to the top of a 0-10 range, so %K ends at 100.
    highs = np.array([10.0] * 6)
    lows = np.array([0.0] * 6)
    closes = np.array([5.0, 5, 5, 10, 10, 10])
    k, d = ind.stochastic(highs, lows, closes, k_period=3, k_smooth=1, d_period=3)
    assert np.isnan(k[:2]).all()
    assert k[2] == 50.0 and k[5] == 100.0
    assert d[5] == pytest.approx(100.0) and np.isnan(d[3])


def test_stochastic_on_a_flat_range_is_not_a_division_by_zero():
    flat = np.array([5.0] * 5)
    k, _ = ind.stochastic(flat, flat, flat, k_period=3, k_smooth=1, d_period=3)
    assert np.isnan(k[2:]).all() or (k[2:] == 50.0).all()


def test_bollinger_bands_are_symmetric_about_the_mean():
    closes = np.array([1.0, 2, 3, 4, 5, 6])
    mid, up, low, width = ind.bollinger(closes, period=3, std=2.0)
    assert np.isnan(mid[:2]).all()
    assert mid[2] == 2.0
    spread = np.std(np.array([1.0, 2, 3]))
    assert up[2] == 2.0 + 2 * spread and low[2] == 2.0 - 2 * spread
    assert width[2] == (up[2] - low[2]) / mid[2]


def test_vwap_resets_each_utc_day():
    times = np.array([0, HOUR, DAY, DAY + HOUR])
    price = np.array([10.0, 20.0, 100.0, 200.0])
    volumes = np.array([1.0, 1.0, 1.0, 1.0])
    out = ind.vwap(price, price, price, volumes, times, anchor="day")
    assert out[0] == 10.0 and out[1] == 15.0  # first day accumulates
    assert out[2] == 100.0 and out[3] == 150.0  # second day starts again


def test_vwap_weighs_by_volume_and_uses_typical_price():
    times = np.array([0, HOUR])
    highs, lows, closes = np.array([12.0, 22.0]), np.array([8.0, 18.0]), np.array([10.0, 20.0])
    out = ind.vwap(highs, lows, closes, np.array([1.0, 3.0]), times, anchor="day")
    assert out[0] == 10.0
    assert out[1] == (10.0 * 1 + 20.0 * 3) / 4


def test_vwap_can_anchor_to_the_week():
    # 1970-01-01 was a Thursday; the week boundary is Monday 1970-01-05.
    times = np.array([0, 4 * DAY, 4 * DAY + HOUR])
    price = np.array([10.0, 100.0, 200.0])
    out = ind.vwap(price, price, price, np.array([1.0, 1.0, 1.0]), times, anchor="week")
    assert out[0] == 10.0 and out[1] == 100.0 and out[2] == 150.0


def test_volume_ratio_compares_with_the_bars_before():
    volumes = np.array([10.0, 10, 10, 30])
    out = ind.volume_ratio(volumes, period=3)
    assert np.isnan(out[:3]).all()
    assert out[3] == 3.0


def test_true_range_accounts_for_gaps():
    highs = np.array([10.0, 20.0])
    lows = np.array([9.0, 19.0])
    closes = np.array([9.5, 19.5])
    tr = ind.true_range(highs, lows, closes)
    assert np.isnan(tr[0])
    assert tr[1] == 20.0 - 9.5


def test_atr_series_excludes_the_bar_it_labels():
    highs = np.array([10.0, 11, 12, 40])
    lows = np.array([9.0, 10, 11, 10])
    closes = np.array([9.5, 10.5, 11.5, 39.0])
    atr = ind.atr_series(highs, lows, closes, period=2)
    assert np.isnan(atr[:2]).all()
    assert atr[3] == np.mean([11.0 - 9.5, 12.0 - 10.5])


def test_crosses_series_needs_a_real_crossing():
    a = np.array([1.0, 2.0, 3.0, 1.0])
    b = np.array([2.0, 2.0, 2.0, 2.0])
    above = ind.crosses_series(a, b, "above")
    below = ind.crosses_series(a, b, "below")
    assert not above[0] and not above[1]  # touching is not crossing
    assert above[2] and not above[3]
    assert below[3] and not below[:3].any()
    # Coming to rest exactly on the line is not a cross either.
    level = ind.crosses_series(np.array([3.0, 2.0]), np.array([2.0, 2.0]), "below")
    assert not level.any()


def test_crosses_series_is_false_wherever_an_input_is_nan():
    a = np.array([np.nan, 1.0, 3.0])
    b = np.array([2.0, 2.0, 2.0])
    assert not ind.crosses_series(a, b, "above")[:2].any()
    assert ind.crosses_series(a, b, "above")[2]


def test_indicator_names_cover_the_new_triggers():
    assert ind.INDICATORS == ("rsi", "ema", "macd", "stochastic", "bollinger", "vwap", "volume", "atr")
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_indicators.py -q`
Expected: failures with `AttributeError: module 'analysis.indicators' has no attribute 'sma'`.

- [ ] **Step 3: Implement** — replace the `INDICATORS` line in `backend/analysis/indicators.py` with the tuple below and append the functions:

```python
INDICATORS = ("rsi", "ema", "macd", "stochastic", "bollinger", "vwap", "volume", "atr")
```

```python
def sma(values: np.ndarray, period: int) -> np.ndarray:
    """Simple moving average, NaN until there are `period` values."""
    values = np.asarray(values, dtype=float)
    out = np.full(values.shape, np.nan)
    if period <= 0 or values.size < period:
        return out
    window = np.convolve(values, np.ones(period) / period, mode="valid")
    out[period - 1:] = window
    return out


def stochastic(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    k_period: int = 14,
    k_smooth: int = 3,
    d_period: int = 3,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Smoothed %K and its %D average.

    %K is where the close sits inside the highest high and lowest low of the
    last k_period bars. A range of zero has no position to report, so it stays
    NaN rather than being called 50 or 100.
    """
    highs = np.asarray(highs, dtype=float)
    lows = np.asarray(lows, dtype=float)
    closes = np.asarray(closes, dtype=float)
    raw = np.full(closes.shape, np.nan)

    for i in range(k_period - 1, closes.size):
        window = slice(i + 1 - k_period, i + 1)
        top, bottom = highs[window].max(), lows[window].min()
        if top > bottom:
            raw[i] = (closes[i] - bottom) / (top - bottom) * 100.0

    k = raw if k_smooth <= 1 else sma(raw, k_smooth)
    return k, sma(k, d_period)


def bollinger(
    closes: np.ndarray,
    period: int = 20,
    std: float = 2.0,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Middle, upper, lower band and bandwidth, as fractions of the middle."""
    closes = np.asarray(closes, dtype=float)
    middle = sma(closes, period)
    deviation = np.full(closes.shape, np.nan)
    for i in range(period - 1, closes.size):
        deviation[i] = closes[i + 1 - period: i + 1].std()
    upper = middle + std * deviation
    lower = middle - std * deviation
    with np.errstate(divide="ignore", invalid="ignore"):
        width = (upper - lower) / middle
    return middle, upper, lower, width


WEEK_MS = 7 * 86_400_000
DAY_MS = 86_400_000
# 1970-01-01 was a Thursday, so Monday is four days in.
WEEK_OFFSET_MS = 4 * DAY_MS


def _session(times: np.ndarray, anchor: str) -> np.ndarray:
    times = np.asarray(times, dtype=np.int64)
    if anchor == "week":
        return (times + WEEK_OFFSET_MS) // WEEK_MS
    return times // DAY_MS


def vwap(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    volumes: np.ndarray,
    times: np.ndarray,
    anchor: str = "day",
) -> np.ndarray:
    """
    Volume-weighted average price since the session opened.

    Crypto never closes, so "the session" is a clock convention: the UTC day,
    or the week beginning Monday - the same anchors charting tools default to.
    Typical price (high, low, close averaged) is the classic weight.
    """
    highs = np.asarray(highs, dtype=float)
    lows = np.asarray(lows, dtype=float)
    closes = np.asarray(closes, dtype=float)
    volumes = np.asarray(volumes, dtype=float)
    typical = (highs + lows + closes) / 3.0
    sessions = _session(times, anchor)

    out = np.full(closes.shape, np.nan)
    price_volume = 0.0
    volume = 0.0
    current = None
    for i in range(closes.size):
        if sessions[i] != current:
            current, price_volume, volume = sessions[i], 0.0, 0.0
        price_volume += typical[i] * volumes[i]
        volume += volumes[i]
        out[i] = price_volume / volume if volume > 0 else typical[i]
    return out


def volume_ratio(volumes: np.ndarray, period: int = 20) -> np.ndarray:
    """This bar's volume over the average of the `period` bars before it."""
    volumes = np.asarray(volumes, dtype=float)
    average = sma(volumes, period)
    out = np.full(volumes.shape, np.nan)
    if volumes.size > period:
        with np.errstate(divide="ignore", invalid="ignore"):
            out[period:] = volumes[period:] / average[period - 1: -1]
        out[np.isinf(out)] = np.nan
    return out


def true_range(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray) -> np.ndarray:
    """True range, NaN on the first bar - it has no previous close."""
    highs = np.asarray(highs, dtype=float)
    lows = np.asarray(lows, dtype=float)
    closes = np.asarray(closes, dtype=float)
    out = np.full(highs.shape, np.nan)
    if highs.size < 2:
        return out
    previous = closes[:-1]
    out[1:] = np.maximum(
        highs[1:] - lows[1:],
        np.maximum(np.abs(highs[1:] - previous), np.abs(lows[1:] - previous)),
    )
    return out


def atr_series(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    period: int = 14,
) -> np.ndarray:
    """
    Average true range of the bars *before* each bar.

    Excluding the current bar is what lets a threshold ask "is this bar bigger
    than what came before it" without the bar inflating its own benchmark.
    """
    ranges = true_range(highs, lows, closes)
    average = sma(ranges, period)
    out = np.full(ranges.shape, np.nan)
    if ranges.size > 1:
        out[1:] = average[:-1]
    return out


def crosses_series(a: np.ndarray, b: np.ndarray, direction: str) -> np.ndarray:
    """
    True on the bar where `a` crossed `b`.

    Strict on both sides: it must have been on the other side before and be
    beyond it now, so a series resting exactly on the other never signals.
    """
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    out = np.zeros(a.shape, dtype=bool)
    if a.size < 2:
        return out
    before, now = a[:-1] - b[:-1], a[1:] - b[1:]
    valid = ~(np.isnan(before) | np.isnan(now))
    if direction == "above":
        out[1:] = valid & (before <= 0) & (now > 0)
    else:
        out[1:] = valid & (before >= 0) & (now < 0)
    return out
```

Add `Tuple` to the module's `typing` import if it is not already there.

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_indicators.py -q`
Expected: all passed (13 new plus the existing ones).

- [ ] **Step 5: Commit**

```bash
git add backend/analysis/indicators.py backend/tests/test_indicators.py
git commit -m "Stochastic, Bollinger, VWAP, volume and ATR series

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: The step schemas

**Files:** Modify `backend/models/rule_schemas.py`; Test `backend/tests/test_rule_steps.py` (create)

**Interfaces:**
- Produces seven models, each with `type` as its discriminator:
  - `EmaCrossStep(type="ema_cross", fast=20, slow=50, cross="above")` — `fast < slow`, `fast >= 1` (1 means the close itself)
  - `MacdCrossStep(type="macd_cross", fast=12, slow=26, signal=9, against="signal"|"zero", cross="above")`
  - `StochCrossStep(type="stoch_cross", k=14, k_smooth=3, d=3, against="d"|"level", level=20.0, cross="above")`
  - `BollingerStep(type="bollinger", band="upper"|"middle"|"lower", cross="above"|"below", period=20, std=2.0)`
  - `BollingerSqueezeStep(type="bollinger_squeeze", period=20, std=2.0, lookback=120)`
  - `VwapCrossStep(type="vwap_cross", anchor="day"|"week", cross="above")`
  - `VolumeSpikeStep(type="volume_spike", multiple=2.0, period=20)`
  - `AtrExpansionStep(type="atr_expansion", multiple=2.0, period=14)`
- Produces `STEP_TYPES: Tuple[str, ...]`, `step_warmup(step: dict) -> int`, and `SequenceStep` extended with all of them.
- `SequenceRuleParams.model_post_init` uses the longest `step_warmup` instead of only indicator periods, and `RuleCreate` refuses a day-anchored VWAP step on the `1d` timeframe.

- [ ] **Step 1: Write the failing tests** — `backend/tests/test_rule_steps.py`:

```python
"""The new sequence steps: what they accept, and what they refuse."""
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis.sequence import describe_steps
from models.rule_schemas import STEP_TYPES, RuleCreate, SequenceRuleParams, step_warmup


def rule(steps, timeframe="1h", **kw):
    return RuleCreate(
        name="t", symbol="BTCUSDT", timeframe=timeframe,
        params={"agent": "sequence", "steps": steps, **kw},
    )


def test_the_mask_dispatch_knows_the_same_step_types():
    from analysis.sequence import MASK_STEPS

    assert MASK_STEPS == STEP_TYPES


def test_every_step_type_is_named():
    assert STEP_TYPES == (
        "candle", "indicator", "structure", "ema_cross", "macd_cross",
        "stoch_cross", "bollinger", "bollinger_squeeze", "vwap_cross",
        "volume_spike", "atr_expansion",
    )


def test_the_rsi_step_keeps_its_old_shape():
    # Rules already armed in production store exactly this.
    step = rule([{"type": "indicator", "indicator": "rsi", "period": 14, "cross": "above", "level": 30}]).params.steps[0]
    assert (step.indicator, step.period, step.cross, step.level) == ("rsi", 14, "above", 30.0)


def test_new_steps_take_their_defaults():
    steps = rule([
        {"type": "ema_cross"}, {"type": "macd_cross"}, {"type": "stoch_cross"},
        {"type": "bollinger"},
    ], lookback=400).params.steps
    assert (steps[0].fast, steps[0].slow, steps[0].cross) == (20, 50, "above")
    assert (steps[1].fast, steps[1].slow, steps[1].signal, steps[1].against) == (12, 26, 9, "signal")
    assert (steps[2].k, steps[2].k_smooth, steps[2].d, steps[2].against, steps[2].level) == (14, 3, 3, "d", 20.0)
    assert (steps[3].band, steps[3].cross, steps[3].period, steps[3].std) == ("upper", "above", 20, 2.0)


def test_a_fast_ema_must_be_faster_than_the_slow_one():
    with pytest.raises(ValidationError, match="faster"):
        rule([{"type": "ema_cross", "fast": 50, "slow": 20}])


def test_price_crossing_an_ema_is_a_fast_period_of_one():
    step = rule([{"type": "ema_cross", "fast": 1, "slow": 200}], lookback=500).params.steps[0]
    assert step.fast == 1


def test_warmup_is_the_longest_of_the_steps():
    assert step_warmup({"type": "candle", "shape": "doji"}) == 2
    assert step_warmup({"type": "indicator", "indicator": "rsi", "period": 14}) == 15
    assert step_warmup({"type": "ema_cross", "fast": 20, "slow": 50}) == 50
    assert step_warmup({"type": "macd_cross", "fast": 12, "slow": 26, "signal": 9}) == 35
    assert step_warmup({"type": "stoch_cross", "k": 14, "k_smooth": 3, "d": 3}) == 20
    assert step_warmup({"type": "bollinger_squeeze", "period": 20, "lookback": 120}) == 140
    assert step_warmup({"type": "volume_spike", "period": 20}) == 21
    assert step_warmup({"type": "atr_expansion", "period": 14}) == 16
    assert step_warmup({"type": "vwap_cross"}) == 2


def test_lookback_must_cover_the_longest_warmup():
    with pytest.raises(ValidationError, match="too short"):
        rule([{"type": "bollinger_squeeze"}], lookback=50)
    assert rule([{"type": "bollinger_squeeze"}], lookback=200).params.steps


def test_a_daily_vwap_rule_on_daily_candles_is_refused():
    with pytest.raises(ValidationError, match="week"):
        rule([{"type": "vwap_cross", "anchor": "day"}], timeframe="1d")
    assert rule([{"type": "vwap_cross", "anchor": "week"}], timeframe="1d").params.steps
    assert rule([{"type": "vwap_cross", "anchor": "day"}], timeframe="4h").params.steps


def test_steps_describe_themselves_in_words():
    said = describe_steps([
        {"type": "ema_cross", "fast": 20, "slow": 50, "cross": "above"},
        {"type": "macd_cross", "against": "zero", "cross": "below"},
        {"type": "stoch_cross", "against": "level", "level": 20, "cross": "above"},
        {"type": "bollinger", "band": "upper", "cross": "above"},
        {"type": "bollinger_squeeze", "lookback": 120},
        {"type": "vwap_cross", "anchor": "day", "cross": "above"},
        {"type": "volume_spike", "multiple": 2.0},
        {"type": "atr_expansion", "multiple": 2.0},
    ])
    assert said == (
        "EMA(20) crosses above EMA(50), then "
        "MACD crosses below zero, then "
        "stochastic %K crosses above 20, then "
        "close crosses above the upper Bollinger band, then "
        "Bollinger squeeze (tightest in 120 bars), then "
        "close crosses above the daily VWAP, then "
        "volume 2x its average, then "
        "range 2x ATR"
    )
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_rule_steps.py -q`
Expected: `ImportError: cannot import name 'STEP_TYPES'`.

- [ ] **Step 3: Implement** in `backend/models/rule_schemas.py`

Insert after `StructureStep`:

```python
class EmaCrossStep(BaseModel):
    """
    One moving average crosses another. A fast period of 1 is the close
    itself, which is how "price crosses the 200 EMA" is expressed.
    """

    type: Literal["ema_cross"] = "ema_cross"
    fast: int = Field(default=20, ge=1, le=400)
    slow: int = Field(default=50, ge=2, le=400)
    cross: Literal["above", "below"] = "above"

    def model_post_init(self, _context: Any) -> None:
        if self.fast >= self.slow:
            raise ValueError(
                f"The fast EMA must be faster than the slow one (got {self.fast} and {self.slow})"
            )


class MacdCrossStep(BaseModel):
    """MACD crosses its signal line, or crosses zero."""

    type: Literal["macd_cross"] = "macd_cross"
    fast: int = Field(default=12, ge=2, le=200)
    slow: int = Field(default=26, ge=3, le=400)
    signal: int = Field(default=9, ge=1, le=100)
    against: Literal["signal", "zero"] = "signal"
    cross: Literal["above", "below"] = "above"

    def model_post_init(self, _context: Any) -> None:
        if self.fast >= self.slow:
            raise ValueError(
                f"MACD's fast length must be shorter than its slow one (got {self.fast} and {self.slow})"
            )


class StochCrossStep(BaseModel):
    """Stochastic %K crosses %D, or crosses a level such as 20 or 80."""

    type: Literal["stoch_cross"] = "stoch_cross"
    k: int = Field(default=14, ge=2, le=200)
    k_smooth: int = Field(default=3, ge=1, le=50)
    d: int = Field(default=3, ge=1, le=50)
    against: Literal["d", "level"] = "d"
    level: float = Field(default=20.0, ge=0, le=100)
    cross: Literal["above", "below"] = "above"


class BollingerStep(BaseModel):
    """The close crosses a Bollinger band."""

    type: Literal["bollinger"] = "bollinger"
    band: Literal["upper", "middle", "lower"] = "upper"
    cross: Literal["above", "below"] = "above"
    period: int = Field(default=20, ge=2, le=400)
    std: float = Field(default=2.0, gt=0, le=6)


class BollingerSqueezeStep(BaseModel):
    """
    Bandwidth at its tightest in `lookback` bars - the coiled-spring setup.
    Directionless on its own, so a signal ending here reads from the bar.
    """

    type: Literal["bollinger_squeeze"] = "bollinger_squeeze"
    period: int = Field(default=20, ge=2, le=400)
    std: float = Field(default=2.0, gt=0, le=6)
    lookback: int = Field(default=120, ge=10, le=1000)


class VwapCrossStep(BaseModel):
    """
    The close crosses the session VWAP. Crypto has no session, so the anchor
    is a clock convention: the UTC day, or the week from Monday.
    """

    type: Literal["vwap_cross"] = "vwap_cross"
    anchor: Literal["day", "week"] = "day"
    cross: Literal["above", "below"] = "above"


class VolumeSpikeStep(BaseModel):
    """Volume at least `multiple` times the average of the bars before it."""

    type: Literal["volume_spike"] = "volume_spike"
    multiple: float = Field(default=2.0, gt=1, le=50)
    period: int = Field(default=20, ge=2, le=400)


class AtrExpansionStep(BaseModel):
    """A bar whose true range is at least `multiple` times the recent ATR."""

    type: Literal["atr_expansion"] = "atr_expansion"
    multiple: float = Field(default=2.0, gt=1, le=20)
    period: int = Field(default=14, ge=2, le=200)
```

Replace the `SequenceStep` union line with:

```python
SequenceStep = Union[
    CandleStep,
    IndicatorStep,
    StructureStep,
    EmaCrossStep,
    MacdCrossStep,
    StochCrossStep,
    BollingerStep,
    BollingerSqueezeStep,
    VwapCrossStep,
    VolumeSpikeStep,
    AtrExpansionStep,
]

STEP_TYPES: Tuple[str, ...] = (
    "candle", "indicator", "structure", "ema_cross", "macd_cross",
    "stoch_cross", "bollinger", "bollinger_squeeze", "vwap_cross",
    "volume_spike", "atr_expansion",
)


def step_warmup(step: Dict[str, Any]) -> int:
    """
    Bars a step needs before it can be judged at all.

    Used to check a rule's lookback covers its slowest step: a Bollinger
    squeeze over 120 bars cannot be answered from 50 bars of history, and a
    rule that can never fire is worse than one that is refused.
    """
    kind = step.get("type", "candle")
    if kind == "indicator":
        return int(step.get("period", 14)) + 1
    if kind == "ema_cross":
        return int(step.get("slow", 50))
    if kind == "macd_cross":
        return int(step.get("slow", 26)) + int(step.get("signal", 9))
    if kind == "stoch_cross":
        return int(step.get("k", 14)) + int(step.get("k_smooth", 3)) + int(step.get("d", 3))
    if kind == "bollinger":
        return int(step.get("period", 20))
    if kind == "bollinger_squeeze":
        return int(step.get("period", 20)) + int(step.get("lookback", 120))
    if kind == "volume_spike":
        return int(step.get("period", 20)) + 1
    if kind == "atr_expansion":
        return int(step.get("period", 14)) + 2
    # Candles, structure and VWAP need the bar and the one before it.
    return 2
```

Add `Tuple` to the `typing` import. Then replace `SequenceRuleParams.model_post_init` with:

```python
    def model_post_init(self, _context: Any) -> None:
        # Pydantic picks the step model from `type`, so a bad `type` is already
        # a 422 by here. What it cannot check is that the lookback leaves room
        # for the slowest step's warm-up plus the window between steps.
        longest = max(step_warmup(s.model_dump()) for s in self.steps)
        needed = longest + self.within_bars * len(self.steps) + 2
        if self.lookback < needed:
            raise ValueError(
                f"lookback {self.lookback} is too short for these steps; "
                f"need at least {needed} bars"
            )
```

Finally, in `RuleCreate`, add:

```python
    def model_post_init(self, _context: Any) -> None:
        # A session VWAP over a single daily candle is that candle's own
        # typical price, so the rule could never mean what it says.
        if self.timeframe == "1d" and self.params.agent == "sequence":
            for step in self.params.steps:
                if getattr(step, "type", None) == "vwap_cross" and step.anchor == "day":
                    raise ValueError(
                        "A day-anchored VWAP means nothing on daily candles; use the week anchor"
                    )
```

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_rule_steps.py -q`
Expected: 9 passed — except `test_steps_describe_themselves_in_words`, which stays red until Task 3.

- [ ] **Step 5: Commit**

```bash
git add backend/models/rule_schemas.py backend/tests/test_rule_steps.py
git commit -m "Eight new sequence step types, with warm-up accounting

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Masks and wording

**Files:** Modify `backend/analysis/sequence.py`; Test `backend/tests/test_sequence.py` (append)

**Interfaces:**
- `step_mask(candles, step)` handles every new `type`, returning a boolean mask the length of `candles`.
- `describe_steps(steps)` produces the sentences pinned by Task 2's wording test.
- Consumes `indicators.stochastic/bollinger/vwap/volume_ratio/atr_series/true_range/crosses_series/ema/macd`.

- [ ] **Step 1: Write the failing tests** (append to `backend/tests/test_sequence.py`)

```python
from analysis.sequence import step_mask

H = 3_600_000
T0 = 1_700_000_000_000 - (1_700_000_000_000 % 86_400_000)  # a UTC midnight


def ohlcv(rows, step_ms=H, start=T0):
    """rows: (open, high, low, close, volume)."""
    return [
        {"time": start + i * step_ms, "open": o, "high": h, "low": l, "close": c, "volume": v}
        for i, (o, h, l, c, v) in enumerate(rows)
    ]


def rising_rows(n, start=100.0, step=1.0, volume=10.0):
    return [(start + i * step, start + i * step + 0.4, start + i * step - 0.4, start + i * step + 0.2, volume)
            for i in range(n)]


def test_ema_cross_fires_once_when_the_fast_line_crosses_up():
    # Falling then rising hard: the fast EMA must cross the slow one exactly once.
    rows = [(100 - i, 100 - i + 0.3, 100 - i - 0.3, 100 - i, 10.0) for i in range(40)]
    rows += [(60 + 4 * i, 60 + 4 * i + 1, 60 + 4 * i - 1, 62 + 4 * i, 10.0) for i in range(30)]
    mask = step_mask(ohlcv(rows), {"type": "ema_cross", "fast": 5, "slow": 20, "cross": "above"})
    assert mask.sum() == 1 and mask[:20].sum() == 0


def test_macd_cross_can_watch_the_signal_line_or_zero():
    rows = [(100 - i, 100 - i + 0.3, 100 - i - 0.3, 100 - i, 10.0) for i in range(60)]
    rows += [(40 + 3 * i, 40 + 3 * i + 1, 40 + 3 * i - 1, 42 + 3 * i, 10.0) for i in range(60)]
    candles = ohlcv(rows)
    signal = step_mask(candles, {"type": "macd_cross", "against": "signal", "cross": "above"})
    zero = step_mask(candles, {"type": "macd_cross", "against": "zero", "cross": "above"})
    assert signal.any() and zero.any()
    # Crossing the signal line leads crossing zero.
    assert int(np.argmax(signal)) < int(np.argmax(zero))


def test_stochastic_crosses_a_level_and_its_d_line():
    rows = [(100.0, 110.0, 90.0, 92.0, 10.0)] * 20 + [(100.0, 110.0, 90.0, 108.0, 10.0)] * 5
    candles = ohlcv(rows)
    level = step_mask(candles, {"type": "stoch_cross", "against": "level", "level": 80, "cross": "above"})
    against_d = step_mask(candles, {"type": "stoch_cross", "against": "d", "cross": "above"})
    assert level.any() and against_d.any()


def test_bollinger_band_cross_and_squeeze():
    quiet = [(100.0, 100.2, 99.8, 100.0, 10.0)] * 60
    breakout = [(100.0, 106.0, 99.9, 105.0, 10.0)]
    candles = ohlcv(quiet + breakout)
    upper = step_mask(candles, {"type": "bollinger", "band": "upper", "cross": "above", "period": 20})
    assert upper[-1] and upper[:-1].sum() == 0
    squeeze = step_mask(candles, {"type": "bollinger_squeeze", "period": 20, "lookback": 25})
    assert squeeze[:-1].any() and not squeeze[-1]


def test_vwap_cross_uses_the_session_anchor():
    # A day of weak closes, then a strong one that lifts the close over VWAP.
    rows = [(100.0, 100.5, 99.5, 99.6, 10.0)] * 5 + [(99.6, 103.0, 99.5, 102.5, 10.0)]
    mask = step_mask(ohlcv(rows), {"type": "vwap_cross", "anchor": "day", "cross": "above"})
    assert mask[-1]


def test_volume_spike_needs_the_multiple_and_takes_no_direction_of_its_own():
    rows = rising_rows(21) + [(120.0, 121.0, 119.0, 120.5, 100.0)]
    mask = step_mask(ohlcv(rows), {"type": "volume_spike", "multiple": 2.0, "period": 20})
    assert mask[-1] and mask[:-1].sum() == 0


def test_atr_expansion_fires_on_an_unusually_wide_bar():
    rows = [(100.0, 100.5, 99.5, 100.0, 10.0)] * 20 + [(100.0, 110.0, 99.0, 109.0, 10.0)]
    mask = step_mask(ohlcv(rows), {"type": "atr_expansion", "multiple": 2.0, "period": 14})
    assert mask[-1] and mask[:-1].sum() == 0


def test_an_unknown_step_type_is_refused_loudly():
    # A typo in a step must not read as "never matches", which would look
    # like a rule that simply never fires.
    with pytest.raises(ValueError, match="Unknown step type"):
        step_mask(ohlcv(rising_rows(30)), {"type": "nonsense"})
```

Add `import numpy as np` and `import pytest` to the test file's imports if they are not already there.

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_sequence.py -q`
Expected: the new tests fail with `ValueError: Unknown step type` from `step_mask`.

- [ ] **Step 3: Implement** in `backend/analysis/sequence.py`

Extend the indicators import to include what the new masks need:

```python
from analysis.indicators import (
    atr_series,
    bollinger,
    crosses,
    crosses_series,
    ema,
    macd,
    rsi,
    stochastic,
    true_range,
    volume_ratio,
    vwap,
)
```

Hoist the series every branch may need: replace

```python
    if kind == "indicator":
        name = step.get("indicator")
        closes = np.array([float(c["close"]) for c in candles], dtype=float)
```

with

```python
    closes = np.array([float(c["close"]) for c in candles], dtype=float)
    highs = np.array([float(c["high"]) for c in candles], dtype=float)
    lows = np.array([float(c["low"]) for c in candles], dtype=float)
    volumes = np.array([float(c["volume"]) for c in candles], dtype=float)
    times = np.array([int(c["time"]) for c in candles], dtype=np.int64)

    if kind == "indicator":
        name = step.get("indicator")
```

Name the step types this module can mask, so the closing raise can list them.
`analysis/` must not import from `models/`, so the tuple is written here as well
as in the schemas, and a test in Task 2 asserts the two cannot drift:

```python
MASK_STEPS = (
    "candle", "indicator", "structure", "ema_cross", "macd_cross", "stoch_cross",
    "bollinger", "bollinger_squeeze", "vwap_cross", "volume_spike", "atr_expansion",
)
```

and end `step_mask` with

```python
    raise ValueError(
        f"Unknown step type {kind!r}. Expected one of: " + ", ".join(MASK_STEPS)
    )
```

Then add the new branches, after the existing `candle`, `indicator` and `structure` branches:

```python
    highs = np.array([float(c["high"]) for c in candles], dtype=float)
    lows = np.array([float(c["low"]) for c in candles], dtype=float)
    volumes = np.array([float(c["volume"]) for c in candles], dtype=float)
    times = np.array([int(c["time"]) for c in candles], dtype=np.int64)

    if kind == "ema_cross":
        fast = closes if int(step.get("fast", 20)) == 1 else ema(closes, int(step.get("fast", 20)))
        slow = ema(closes, int(step.get("slow", 50)))
        return crosses_series(fast, slow, step.get("cross", "above"))

    if kind == "macd_cross":
        line, signal_line, _ = macd(
            closes,
            fast=int(step.get("fast", 12)),
            slow=int(step.get("slow", 26)),
            signal=int(step.get("signal", 9)),
        )
        other = np.zeros(line.shape) if step.get("against") == "zero" else signal_line
        return crosses_series(line, other, step.get("cross", "above"))

    if kind == "stoch_cross":
        k, d = stochastic(
            highs, lows, closes,
            k_period=int(step.get("k", 14)),
            k_smooth=int(step.get("k_smooth", 3)),
            d_period=int(step.get("d", 3)),
        )
        if step.get("against") == "level":
            return crosses(k, float(step.get("level", 20.0)), step.get("cross", "above"))
        return crosses_series(k, d, step.get("cross", "above"))

    if kind == "bollinger":
        middle, upper, lower, _ = bollinger(
            closes, period=int(step.get("period", 20)), std=float(step.get("std", 2.0))
        )
        band = {"upper": upper, "middle": middle, "lower": lower}[step.get("band", "upper")]
        return crosses_series(closes, band, step.get("cross", "above"))

    if kind == "bollinger_squeeze":
        _, _, _, width = bollinger(
            closes, period=int(step.get("period", 20)), std=float(step.get("std", 2.0))
        )
        lookback = int(step.get("lookback", 120))
        out = np.zeros(closes.shape, dtype=bool)
        for i in range(closes.size):
            window = width[max(0, i + 1 - lookback): i + 1]
            if np.isnan(width[i]) or np.isnan(window).all():
                continue
            # The tightest bandwidth of the window, this bar included.
            out[i] = width[i] <= np.nanmin(window)
        return out

    if kind == "vwap_cross":
        line = vwap(highs, lows, closes, volumes, times, anchor=step.get("anchor", "day"))
        return crosses_series(closes, line, step.get("cross", "above"))

    if kind == "volume_spike":
        ratio = volume_ratio(volumes, period=int(step.get("period", 20)))
        with np.errstate(invalid="ignore"):
            return np.nan_to_num(ratio, nan=0.0) >= float(step.get("multiple", 2.0))

    if kind == "atr_expansion":
        ranges = true_range(highs, lows, closes)
        unit = atr_series(highs, lows, closes, period=int(step.get("period", 14)))
        with np.errstate(invalid="ignore"):
            wide = np.nan_to_num(ranges, nan=0.0) >= float(step.get("multiple", 2.0)) * np.nan_to_num(unit, nan=np.inf)
        return wide
```

Extend `describe_steps` with the wording the Task 2 test pins:

```python
        elif step.get("type") == "ema_cross":
            fast = int(step.get("fast", 20))
            left = "close" if fast == 1 else f"EMA({fast})"
            parts.append(f"{left} crosses {step.get('cross', 'above')} EMA({step.get('slow', 50)})")
        elif step.get("type") == "macd_cross":
            against = "zero" if step.get("against") == "zero" else "its signal line"
            parts.append(f"MACD crosses {step.get('cross', 'above')} {against}")
        elif step.get("type") == "stoch_cross":
            if step.get("against") == "level":
                target = f"{float(step.get('level', 20)):g}"
            else:
                target = "%D"
            parts.append(f"stochastic %K crosses {step.get('cross', 'above')} {target}")
        elif step.get("type") == "bollinger":
            parts.append(
                f"close crosses {step.get('cross', 'above')} the {step.get('band', 'upper')} Bollinger band"
            )
        elif step.get("type") == "bollinger_squeeze":
            parts.append(f"Bollinger squeeze (tightest in {int(step.get('lookback', 120))} bars)")
        elif step.get("type") == "vwap_cross":
            anchor = "weekly" if step.get("anchor") == "week" else "daily"
            parts.append(f"close crosses {step.get('cross', 'above')} the {anchor} VWAP")
        elif step.get("type") == "volume_spike":
            parts.append(f"volume {float(step.get('multiple', 2.0)):g}x its average")
        elif step.get("type") == "atr_expansion":
            parts.append(f"range {float(step.get('multiple', 2.0)):g}x ATR")
```

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_sequence.py tests/test_rule_steps.py -q`
Expected: all passed, including Task 2's wording test.

- [ ] **Step 5: Commit**

```bash
git add backend/analysis/sequence.py backend/tests/test_sequence.py
git commit -m "Match and describe the new indicator steps

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: Direction, and the engine end to end

**Files:** Modify `backend/services/rule_decision.py`; Test `backend/tests/test_rule_decision.py` (append)

**Interfaces:** `sequence_candidates` reads a signal's direction from its last step: `cross == "above"` → bullish, `"below"` → bearish for the four crossing steps and the Bollinger band step; a squeeze, a volume spike and an ATR expansion take the colour of the bar they fired on. Produces `step_direction(step: dict, candle: dict) -> str`.

- [ ] **Step 1: Write the failing tests** (append)

```python
from services.rule_decision import step_direction

BULL_BAR = {"open": 100.0, "close": 101.0, "high": 101.5, "low": 99.5, "time": 0, "volume": 1.0}
BEAR_BAR = {"open": 101.0, "close": 100.0, "high": 101.5, "low": 99.5, "time": 0, "volume": 1.0}


def test_a_cross_reads_its_own_direction():
    assert step_direction({"type": "ema_cross", "cross": "above"}, BEAR_BAR) == "bullish"
    assert step_direction({"type": "macd_cross", "cross": "below"}, BULL_BAR) == "bearish"
    assert step_direction({"type": "vwap_cross", "cross": "above"}, BEAR_BAR) == "bullish"
    assert step_direction({"type": "bollinger", "cross": "below"}, BULL_BAR) == "bearish"


def test_directionless_steps_take_the_colour_of_the_bar():
    for kind in ("volume_spike", "atr_expansion", "bollinger_squeeze"):
        assert step_direction({"type": kind}, BULL_BAR) == "bullish"
        assert step_direction({"type": kind}, BEAR_BAR) == "bearish"
    doji = {"open": 100.0, "close": 100.0, "high": 101.0, "low": 99.0, "time": 0, "volume": 1.0}
    assert step_direction({"type": "volume_spike"}, doji) == "neutral"


def test_the_old_step_types_are_unchanged():
    assert step_direction({"type": "indicator", "cross": "above"}, BEAR_BAR) == "bullish"
    assert step_direction({"type": "structure", "side": "bearish"}, BULL_BAR) == "bearish"
    assert step_direction({"type": "candle", "shape": "hammer"}, BEAR_BAR) == "bullish"
    assert step_direction({"type": "candle", "shape": "doji"}, BULL_BAR) == "neutral"
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_rule_decision.py -q`
Expected: `ImportError: cannot import name 'step_direction'`.

- [ ] **Step 3: Implement** in `backend/services/rule_decision.py`

Add above `sequence_candidates`:

```python
# Steps that say which way they point. Everything else is read from the bar.
CROSSING_STEPS = ("indicator", "ema_cross", "macd_cross", "stoch_cross", "bollinger", "vwap_cross")


def step_direction(step: Dict[str, Any], candle: Dict[str, Any]) -> str:
    """
    Which way a sequence points, judged by its final step.

    A crossing knows its own direction. A squeeze, a volume spike or a range
    expansion does not - they say "something is happening", not which way - so
    they take the colour of the bar they fired on.
    """
    kind = step.get("type", "candle")
    if kind in CROSSING_STEPS:
        return "bullish" if step.get("cross", "above") == "above" else "bearish"
    if kind == "structure":
        return step.get("side", "neutral")
    if kind == "candle":
        return SHAPE_BIAS.get(step.get("shape", ""), "neutral")

    close, opened = float(candle["close"]), float(candle["open"])
    if close > opened:
        return "bullish"
    if close < opened:
        return "bearish"
    return "neutral"
```

In `sequence_candidates`, replace the direction block

```python
    last = steps[-1]
    if last.get("type") == "indicator":
        direction = "bullish" if last.get("cross") == "above" else "bearish"
    elif last.get("type") == "structure":
        direction = last.get("side", "neutral")
    else:
        direction = SHAPE_BIAS.get(last.get("shape", ""), "neutral")
```

with

```python
    direction = step_direction(steps[-1], candles[picked[-1]])
```

- [ ] **Step 4: Run the whole backend suite**

Run: `python -m pytest -q`
Expected: 0 failures, with the count risen by the tests these tasks added (425 before).

- [ ] **Step 5: Commit**

```bash
git add backend/services/rule_decision.py backend/tests/test_rule_decision.py
git commit -m "Direction for the new steps, from the cross or from the bar

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: Chat can draft them

**Files:** Modify `backend/agents/rule_parser.py`; Test `backend/tests/test_rule_parser.py` (append)

**Interfaces:** The prompt's Form A gains every new step type with its JSON shape and the words traders use for it. `parse_draft` needs no change — the schema already accepts the steps — so the tests feed canned model JSON, as the existing ones do.

- [ ] **Step 1: Write the failing tests** (append)

```python
def test_a_draft_may_use_the_new_indicator_steps():
    raw = json.dumps({
        "name": "MACD cross", "symbol": "ETHUSDT", "timeframe": "15m",
        "params": {"agent": "sequence", "within_bars": 3, "lookback": 300,
                   "steps": [{"type": "macd_cross", "against": "signal", "cross": "above"}]},
    })
    draft = parse_draft(raw, "BTCUSDT", "1h")
    assert draft.params.agent == "sequence"
    assert draft.params.steps[0].type == "macd_cross"
    assert "MACD crosses above its signal line" in describe_draft(draft)


def test_a_draft_chaining_a_squeeze_and_a_breakout_is_valid():
    raw = json.dumps({
        "name": "squeeze break", "symbol": "BTCUSDT", "timeframe": "1h",
        "params": {"agent": "sequence", "within_bars": 5, "lookback": 400,
                   "steps": [{"type": "bollinger_squeeze"},
                             {"type": "bollinger", "band": "upper", "cross": "above"}]},
    })
    draft = parse_draft(raw, "BTCUSDT", "1h")
    assert [s.type for s in draft.params.steps] == ["bollinger_squeeze", "bollinger"]


def test_the_prompt_teaches_every_step_type():
    from agents.rule_parser import SYSTEM_PROMPT
    from models.rule_schemas import STEP_TYPES

    for kind in STEP_TYPES:
        assert kind in SYSTEM_PROMPT, kind
    for word in ("VWAP", "squeeze", "volume", "stochastic", "MACD", "EMA"):
        assert word.lower() in SYSTEM_PROMPT.lower(), word
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_rule_parser.py -q`
Expected: the prompt test fails (the new step names are absent).

- [ ] **Step 3: Implement** — in `backend/agents/rule_parser.py`, extend the Form A step list in `SYSTEM_PROMPT_TEMPLATE` with:

```
  {"type":"ema_cross","fast":20,"slow":50,"cross":"above"}            EMA cross; fast 1 means the close, so "price crosses the 200 EMA" is fast 1, slow 200
  {"type":"macd_cross","fast":12,"slow":26,"signal":9,"against":"signal"|"zero","cross":"above"}
  {"type":"stoch_cross","k":14,"k_smooth":3,"d":3,"against":"d"|"level","level":20,"cross":"above"}   stochastic; "oversold cross" is against level 20 above
  {"type":"bollinger","band":"upper"|"middle"|"lower","cross":"above","period":20,"std":2}            close crossing a band
  {"type":"bollinger_squeeze","period":20,"std":2,"lookback":120}      bands at their tightest: a squeeze, coiling, low volatility
  {"type":"vwap_cross","anchor":"day"|"week","cross":"above"}          close crossing session VWAP; day anchor is invalid on the 1d timeframe
  {"type":"volume_spike","multiple":2,"period":20}                     volume spike, unusual volume, volume climax
  {"type":"atr_expansion","multiple":2,"period":14}                    range expansion, wide bar, volatility expansion
```

and add to the prompt's guidance: *"Pick the step that matches the words used. Golden cross means EMA 50 crossing above EMA 200. Oversold stochastic means against level 20 crossing above; overbought means level 80 crossing below. Set lookback high enough for the slowest step (a Bollinger squeeze over 120 bars needs 400)."*

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_rule_parser.py -q`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add backend/agents/rule_parser.py backend/tests/test_rule_parser.py
git commit -m "Teach the chat rule parser the new triggers

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: The client's step types

**Files:** Modify `frontend/lib/rules.ts`

**Interfaces:** Mirrors the new step models so a chat draft type-checks in the browser, and `SequenceStep` becomes the full union. No behaviour changes; the draft card already renders the server's sentence.

- [ ] **Step 1: Implement** — in `frontend/lib/rules.ts`, after `StructureStep`, add:

```ts
export interface EmaCrossStep {
  type: "ema_cross"
  /** 1 means the close itself, so "price crosses the 200 EMA". */
  fast: number
  slow: number
  cross: "above" | "below"
}

export interface MacdCrossStep {
  type: "macd_cross"
  fast?: number
  slow?: number
  signal?: number
  against: "signal" | "zero"
  cross: "above" | "below"
}

export interface StochCrossStep {
  type: "stoch_cross"
  k?: number
  k_smooth?: number
  d?: number
  against: "d" | "level"
  level?: number
  cross: "above" | "below"
}

export interface BollingerStep {
  type: "bollinger"
  band: "upper" | "middle" | "lower"
  cross: "above" | "below"
  period?: number
  std?: number
}

export interface BollingerSqueezeStep {
  type: "bollinger_squeeze"
  period?: number
  std?: number
  lookback?: number
}

export interface VwapCrossStep {
  type: "vwap_cross"
  /** A day anchor is refused on the 1d timeframe. */
  anchor: "day" | "week"
  cross: "above" | "below"
}

export interface VolumeSpikeStep {
  type: "volume_spike"
  multiple?: number
  period?: number
}

export interface AtrExpansionStep {
  type: "atr_expansion"
  multiple?: number
  period?: number
}
```

and replace the `SequenceStep` type with:

```ts
export type SequenceStep =
  | CandleStep
  | IndicatorStep
  | StructureStep
  | EmaCrossStep
  | MacdCrossStep
  | StochCrossStep
  | BollingerStep
  | BollingerSqueezeStep
  | VwapCrossStep
  | VolumeSpikeStep
  | AtrExpansionStep
```

- [ ] **Step 2: Verify**

Run (from `frontend/`): `npx tsc --noEmit -p .` — only the pre-existing `tests/sw.test.ts` error; `npx vitest run` — 62 passed.

- [ ] **Step 3: Commit**

```bash
git add frontend/lib/rules.ts
git commit -m "Mirror the new sequence steps in the client types

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 7: Ship and verify on production

- [ ] **Step 1:** Backend suite green with 0 failures; frontend 62; `npx next build` clean; secret scan of the diff shows nothing.
- [ ] **Step 2:** Push `feature/indicator-triggers`, open PR "Eight new indicator triggers for rules", merge to main, push GitLab.
- [ ] **Step 3: Deploy.** If the GitHub deploy key is in place, `sudo git pull --ff-only` on the VM; otherwise ship a bundle as in the backtesting slices, then rebuild and restart `backend` and `backtester`, and confirm both healthy.
- [ ] **Step 4: Prove each trigger fires on real data.** With a throwaway session on the VM (token in a shell variable only), for each of the eight step types: `POST /api/rules` with a one-step sequence rule on BTCUSDT 1h, then `POST /api/rules/{id}/test` and record `would_fire` and `blocked_by` — every one must answer without a 4xx/5xx, and `blocked_by` must be `no_match` or absent, never an error. Then delete the rules. Also confirm `POST /api/rules` with `{"type": "vwap_cross", "anchor": "day"}` on `1d` returns **422**.
- [ ] **Step 5: Prove one of them backtests.** Run a backtest of an EMA-cross rule (fast 20, slow 50) on BTCUSDT 1h with tuning off, and confirm the report has trades in both periods and a finite expectancy. Delete the job.
- [ ] **Step 6: Prove chat can draft one.** `POST /api/chat/ask` with "alert me when price crosses above the weekly VWAP on ETH 1h" and confirm the reply carries a `rule_draft` whose step type is `vwap_cross`.
