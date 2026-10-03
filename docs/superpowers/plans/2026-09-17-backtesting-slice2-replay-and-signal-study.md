# Backtesting Slice 2: Replay and Signal Study — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A signed-in trader presses **Backtest** on any rule or chat draft and, a few minutes later, reads whether its signal predicted anything — forward returns against the market baseline, with a bootstrap confidence interval, reported separately on seen and unseen history.

**Architecture:** The live engine's decisions are extracted into a pure module (`services/rule_decision.py`: candidate lists, filter, persistence/cooldown decision) that both `RuleEngine` and the new `backtest/` package call, so a replay runs the exact code that fires alerts. The worker claims jobs from a `backtest_jobs` table, replays history in chunks into a **candidate tape** (cached in `signal_tapes`), turns the tape into signals with bar-time clocks, and writes a signal-study report. A FastAPI controller creates and reads jobs per wallet; a sheet in the frontend starts them and polls.

**Tech Stack:** Python 3.11, FastAPI, asyncpg, TimescaleDB, numpy, APScheduler 3, pytest + pytest-asyncio (`asyncio_mode = auto`); Next.js 15, React 19, shadcn/ui (`Sheet`, `Progress`, `Button`), vitest.

**Spec:** `docs/superpowers/specs/2026-09-17-backtesting-design.md` — sections "Targeted refactor", "2. Replay and candidate tape", "3. Signal study", "API", "UI", "Error handling", "Testing", "Slices → 2". Slice 1 (history store, worker container) is live: `HistoryRepository.load/coverage`, `TIMEFRAME_MS`, `worker.py`, `GET /api/history/coverage` (cached), `backtester` compose service.

## Global Constraints

- **Refactor safety:** `backend/tests/test_rule_engine.py` passes **unchanged** after Tasks 1–2. Do not edit that file.
- `services/rule_decision.py` and everything under `backend/backtest/` import **no database, network or wall-clock code**.
- Replay window at bar `i` is exactly the live window: `candles[i + 1 - (lookback - 1) : i + 1]` (the sweep fetches `lookback` candles and drops the forming one). First evaluated index is `lookback - 2`.
- Backtest timeframes: `5m`, `15m`, `1h`, `1d`. `MIN_EVALUATED_BARS = 300` beyond the window.
- Study horizons `(1, 5, 10, 20)` bars; headline horizon `10`; excursions over `20` bars in ATR(14) units; bootstrap `2000` resamples, seed `7`; `MIN_SIGNALS = 30`.
- One queued-or-running job per wallet (**429**); a job over **3600 s** fails with `timeout`.
- Job statuses: `queued, replaying, studying, tuning, done, failed, cancelled` (`tuning` is unused until slice 4 but allowed now so no later migration is needed).
- JSON written to Postgres must contain no NaN/Infinity: round through `_r()` which maps non-finite to `None`.
- Commits end with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`; scan staged diffs for `csk-`, `gsk_`, `JWT_SECRET=` before committing.

**Running tests.** Backend, from `backend/`, with a Python 3.11 env holding `requirements.txt` + `pytest pytest-asyncio` (the checked-in `.venv` is broken; recreate with `uv venv --python 3.11 .venv && uv pip install --python .venv/Scripts/python.exe -r requirements.txt pytest pytest-asyncio`): `.venv/Scripts/python.exe -m pytest -q`. Baseline: **334 passed**. Frontend, from `frontend/`: `npx vitest run` (baseline **50 passed**) and `npx tsc --noEmit -p .` (one pre-existing error in `tests/sw.test.ts` is expected and not ours).

## Decisions this plan makes where the spec was silent or had to bend

Record these in the spec in Task 12.

1. **`proximity_pct` is a detector parameter**, not a post-filter: approach candidates are recorded only within the rule's proximity, and `proximity_pct` is part of the tape key. Storing every level on every bar made tapes tens of MB. Filters left for tuning: pattern `min_confidence`, liquidity `min_strength`.
2. **The study counts distinct setups.** A live rule re-fires on every bar its setup persists (dedup is per bar); consecutive fires of one setup are one observation, not many, or the confidence interval is falsely narrow. The report shows both `fires` and `setups`.
3. **Seen signals whose horizon crosses the split are excluded at that horizon**, so no seen statistic reads an unseen price.
4. **The worker requeues every running job at start.** There is one worker; a running status after a restart always means an interrupted job.
5. **One `status` column** carries the stage; there is no separate `stage` column.

## File Structure

| File | Responsibility |
|---|---|
| Create `backend/services/rule_decision.py` | Pure: candidates, `first_passing`, `FiringState`, `decide`, identity helpers, blocked reasons. |
| Modify `backend/services/rule_engine.py` | Call `rule_decision`; keep public names (`_match_liquidity`, `_pattern_identity`, `BLOCKED_*`, `Signal`, `RuleEngine`). |
| Create `backend/db/migrations/005_backtests.sql` | `backtest_jobs`, `signal_tapes`. |
| Create `backend/repositories/backtest_repository.py` | Job and tape SQL; tape gzip codec. |
| Create `backend/models/backtest_schemas.py` | `BacktestCreate`, `window_size`, `MIN_EVALUATED_BARS`, `BACKTEST_TIMEFRAMES`. |
| Create `backend/backtest/__init__.py` (empty), `backtest/replay.py`, `backtest/signals.py`, `backtest/study.py`, `backtest/runner.py` | Replay → tape; tape → signals; signals → study; orchestration. |
| Modify `backend/worker.py` | Job loop, tape eviction job. |
| Create `backend/controllers/backtest_controller.py`; modify `controllers/__init__.py`, `main.py` | API. |
| Create `backend/tests/walks.py` | Deterministic random-walk candles for tests. |
| Create tests `test_rule_decision.py`, `test_backtest_repository.py`, `test_backtest_schemas.py`, `test_backtest_replay.py`, `test_backtest_signals.py`, `test_backtest_study.py`, `test_backtest_runner.py`, `test_backtest_controller.py`; modify `test_worker.py`, `test_migrations.py`, `test_app_imports.py` | Tests. |
| Modify `frontend/lib/rules.ts` | Export auth helpers. |
| Create `frontend/lib/backtests.ts`, `frontend/components/backtest-sheet.tsx`, `frontend/tests/backtests.test.ts` | Client, sheet, tests. |
| Modify `frontend/components/analysis-panel.tsx`, `frontend/components/chat-panel.tsx` | Backtest buttons. |

---

### Task 1: The pure firing decision

**Files:**
- Create: `backend/services/rule_decision.py`
- Modify: `backend/services/rule_engine.py:14-33` (imports, constants), `:217-322` (`evaluate_rule` body after matching)
- Test: `backend/tests/test_rule_decision.py`

**Interfaces:**
- Produces (in `services.rule_decision`):
  - `BLOCKED_NO_MATCH = "no_match"`, `BLOCKED_PERSISTENCE = "persistence"`, `BLOCKED_COOLDOWN = "cooldown"`, `BLOCKED_DEDUP = "dedup"`
  - `@dataclass(frozen=True) FiringState(pending_identity: Optional[str] = None, pending_seen: int = 0, last_bar_time: Optional[datetime] = None, last_fired_at: Optional[datetime] = None)`
  - `@dataclass(frozen=True) Decision(state: FiringState, blocked: Optional[str])` — `blocked is None` means it fires. `state.last_fired_at` is never changed by `decide`; the caller records a fire.
  - `decide(state, identity: Optional[str], bar_time: datetime, *, persist_bars: int, cooldown_secs: int, now: datetime) -> Decision`
  - `state_from_rule(rule: Dict) -> FiringState`, `pending_dict(state: FiringState) -> Optional[Dict]`
- `services.rule_engine` keeps exporting `BLOCKED_*` (re-imported from `rule_decision`).

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_rule_decision.py`:

```python
"""The engine's decisions with no database and no clock of their own."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.rule_decision import (
    BLOCKED_COOLDOWN,
    BLOCKED_NO_MATCH,
    BLOCKED_PERSISTENCE,
    FiringState,
    decide,
    pending_dict,
    state_from_rule,
)

T = datetime(2026, 1, 1, tzinfo=timezone.utc)
HOUR = timedelta(hours=1)


def run(state, identity, bar, persist=0, cooldown=0, now=None):
    return decide(state, identity, bar, persist_bars=persist, cooldown_secs=cooldown, now=now or bar + HOUR)


def test_no_match_clears_the_streak_and_records_the_bar():
    d = run(FiringState(pending_identity="a", pending_seen=2, last_bar_time=T), None, T + HOUR)
    assert d.blocked == BLOCKED_NO_MATCH
    assert d.state.pending_identity is None and d.state.last_bar_time == T + HOUR


def test_without_persistence_a_match_fires_at_once():
    d = run(FiringState(), "a", T)
    assert d.blocked is None
    assert (d.state.pending_identity, d.state.pending_seen) == ("a", 1)


def test_persistence_needs_the_setup_to_survive_a_close():
    first = run(FiringState(), "a", T, persist=1)
    assert first.blocked == BLOCKED_PERSISTENCE
    second = run(first.state, "a", T + HOUR, persist=1)
    assert second.blocked is None and second.state.pending_seen == 2


def test_re_evaluating_the_same_bar_does_not_advance_the_streak():
    first = run(FiringState(), "a", T, persist=1)
    again = run(first.state, "a", T, persist=1)
    assert again.blocked == BLOCKED_PERSISTENCE and again.state.pending_seen == 1


def test_a_different_setup_restarts_the_streak():
    first = run(FiringState(), "a", T, persist=1)
    other = run(first.state, "b", T + HOUR, persist=1)
    assert other.blocked == BLOCKED_PERSISTENCE and other.state.pending_seen == 1


def test_cooldown_is_measured_against_the_clock_it_is_given():
    fired = FiringState(last_fired_at=T)
    assert run(fired, "a", T, cooldown=7200, now=T + HOUR).blocked == BLOCKED_COOLDOWN
    assert run(fired, "a", T, cooldown=7200, now=T + 2 * HOUR).blocked is None


def test_decide_never_records_a_fire_itself():
    d = run(FiringState(), "a", T)
    assert d.state.last_fired_at is None


def test_rule_state_round_trip():
    rule = {"pending": {"identity": "x", "seen": 3}, "last_candle_time": T, "last_fired_at": None}
    state = state_from_rule(rule)
    assert state == FiringState("x", 3, T, None)
    assert pending_dict(state) == {"identity": "x", "seen": 3}
    assert pending_dict(FiringState()) is None
    assert state_from_rule({"pending": None, "last_candle_time": None, "last_fired_at": None}) == FiringState()
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_rule_decision.py -q`
Expected: collection error `ModuleNotFoundError: No module named 'services.rule_decision'`.

- [ ] **Step 3: Create `backend/services/rule_decision.py`**

```python
"""
The pure half of the rule engine: what matched, and whether it fires.

RuleEngine reads candles and writes rule state to the database; what it decides
lives here, with no I/O and no clock of its own. That is what lets a backtest
replay history through exactly the decisions the live engine makes - the
replay passes each bar's close as "now", the sweep passes the wall clock.
"""
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Dict, Optional

# Reasons a matching signal still did not fire. Surfaced by the test endpoint so
# a user can tell "my rule is wrong" from "my rule already fired".
BLOCKED_NO_MATCH = "no_match"
BLOCKED_PERSISTENCE = "persistence"
BLOCKED_COOLDOWN = "cooldown"
BLOCKED_DEDUP = "dedup"


@dataclass(frozen=True)
class FiringState:
    """What the engine remembers about a rule between bars."""

    pending_identity: Optional[str] = None
    pending_seen: int = 0
    last_bar_time: Optional[datetime] = None
    last_fired_at: Optional[datetime] = None


@dataclass(frozen=True)
class Decision:
    state: FiringState
    blocked: Optional[str]


def state_from_rule(rule: Dict[str, Any]) -> FiringState:
    pending = rule.get("pending") or {}
    return FiringState(
        pending_identity=pending.get("identity"),
        pending_seen=int(pending.get("seen", 1)) if pending else 0,
        last_bar_time=rule.get("last_candle_time"),
        last_fired_at=rule.get("last_fired_at"),
    )


def pending_dict(state: FiringState) -> Optional[Dict[str, Any]]:
    if state.pending_identity is None:
        return None
    return {"identity": state.pending_identity, "seen": state.pending_seen}


def decide(
    state: FiringState,
    identity: Optional[str],
    bar_time: datetime,
    *,
    persist_bars: int,
    cooldown_secs: int,
    now: datetime,
) -> Decision:
    """
    Whether a setup seen on `bar_time` fires, and the state to carry forward.

    Persistence counts consecutive closed bars showing the same setup; a
    re-evaluation of a bar already counted does not inflate the streak.
    Cooldown is measured from the last fire to `now`. Recording a fire is the
    caller's job, because only the caller knows whether the fire happened.
    """
    if identity is None:
        return Decision(
            replace(state, pending_identity=None, pending_seen=0, last_bar_time=bar_time),
            BLOCKED_NO_MATCH,
        )

    seen = 1
    if persist_bars:
        same_setup = state.pending_identity == identity
        advanced = state.last_bar_time is None or state.last_bar_time < bar_time
        if same_setup and advanced:
            seen = state.pending_seen + 1
        elif same_setup:
            seen = state.pending_seen

    carried = replace(state, pending_identity=identity, pending_seen=seen, last_bar_time=bar_time)

    if persist_bars and seen <= persist_bars:
        return Decision(carried, BLOCKED_PERSISTENCE)

    if cooldown_secs and state.last_fired_at is not None:
        if (now - state.last_fired_at).total_seconds() < cooldown_secs:
            return Decision(carried, BLOCKED_COOLDOWN)

    return Decision(carried, None)
```

- [ ] **Step 4: Route `RuleEngine.evaluate_rule` through `decide`**

In `backend/services/rule_engine.py`, replace the four `BLOCKED_* = ...` assignments (lines 28–33, with their comment) with:

```python
from services.rule_decision import (  # noqa: F401  (BLOCKED_* are re-exported)
    BLOCKED_COOLDOWN,
    BLOCKED_DEDUP,
    BLOCKED_NO_MATCH,
    BLOCKED_PERSISTENCE,
    decide,
    pending_dict,
    state_from_rule,
)
```

Then replace everything in `evaluate_rule` from `        if matched is None:` down to its final `        return signal, None` with:

```python
        identity = matched[0] if matched is not None else None
        decision = decide(
            state_from_rule(rule),
            identity,
            candle_time,
            persist_bars=int(rule["persist_bars"] or 0),
            cooldown_secs=int(rule["cooldown_secs"] or 0),
            now=datetime.now(timezone.utc),
        )
        if not dry_run:
            # Also clears a half-built streak when the setup is gone.
            await RuleRepository.set_pending(rule["id"], pending_dict(decision.state), candle_time)

        if matched is None:
            return None, BLOCKED_NO_MATCH

        identity, direction, provisional, evidence = matched
        signal = Signal(
            rule_id=str(rule["id"]),
            agent=agent,
            symbol=rule["symbol"],
            timeframe=rule["timeframe"],
            candle_time=candle_time,
            identity=identity,
            direction=direction,
            price=float(closed["close"]),
            provisional=provisional,
            evidence=evidence,
        )

        if decision.blocked is not None:
            return signal, decision.blocked

        if dry_run and await RuleEventRepository.exists(signal.dedup_key()):
            return signal, BLOCKED_DEDUP

        return signal, None
```

- [ ] **Step 5: Run the new and the pinned suites**

Run: `.venv/Scripts/python.exe -m pytest tests/test_rule_decision.py tests/test_rule_engine.py -q`
Expected: all passed (8 new + the existing engine tests), `test_rule_engine.py` untouched (`git diff --stat tests/test_rule_engine.py` prints nothing).

- [ ] **Step 6: Commit**

```bash
git add backend/services/rule_decision.py backend/services/rule_engine.py backend/tests/test_rule_decision.py
git commit -m "Extract the rule engine's firing decision into a pure function

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Candidates, then a filter

**Files:**
- Modify: `backend/services/rule_decision.py` (append), `backend/services/rule_engine.py:14-26` (imports) and `:76-211` (helpers and matchers)
- Test: `backend/tests/test_rule_decision.py` (append)

**Interfaces:**
- Produces (in `services.rule_decision`):
  - `@dataclass(frozen=True) Candidate(identity: str, direction: str, provisional: bool, evidence: Dict[str, Any], confidence: Optional[float] = None, strength: Optional[str] = None)`
  - `pattern_identity(pattern: Dict) -> str`, `strong_enough(strength: str, minimum: str) -> bool`, `candle_time(candle: Dict) -> datetime`
  - `pattern_candidates(params, patterns) -> List[Candidate]` — kinds and states only; detector order.
  - `liquidity_candidates(params, levels, closes) -> List[Candidate]` — side, event and **proximity** only; strength recorded.
  - `sequence_candidates(params, candles) -> List[Candidate]` — zero or one.
  - `first_passing(agent: str, params: Dict, candidates: Sequence[Candidate]) -> Optional[Candidate]` — applies `min_confidence` (pattern) or `min_strength` (liquidity).
  - `as_match(candidate: Optional[Candidate]) -> Optional[Tuple[str, str, bool, Dict]]`
- `services.rule_engine` keeps `_match_pattern`, `_match_liquidity`, `_match_sequence`, `_pattern_identity`, `_strong_enough`, `_candle_time` as thin wrappers/aliases.

- [ ] **Step 1: Write the failing tests** (append to `backend/tests/test_rule_decision.py`)

```python
from services.rule_decision import (
    Candidate,
    first_passing,
    liquidity_candidates,
    pattern_candidates,
    sequence_candidates,
)


def pat(kind="W", state="confirmed", confidence=80.0, t0=1000):
    keys = ("low1", "peak", "low2") if kind == "W" else ("high1", "trough", "high2")
    return {
        "kind": kind, "state": state, "confidence": confidence,
        "points": {k: {"time": t0 + i, "price": 100.0} for i, k in enumerate(keys)},
        "neckline": 105.0, "target": 110.0,
    }


def test_pattern_candidates_ignore_confidence_and_keep_detector_order():
    params = {"kinds": ["W"], "states": ["confirmed"], "min_confidence": 70}
    cands = pattern_candidates(params, [pat(confidence=50, t0=1), pat(kind="M"), pat(confidence=90, t0=2)])
    assert [c.confidence for c in cands] == [50.0, 90.0]
    chosen = first_passing("pattern", params, cands)
    assert chosen.confidence == 90.0 and chosen.direction == "bullish"


def test_liquidity_approach_candidates_keep_weak_levels_but_not_far_ones():
    levels = {"support_levels": [
        {"price": 99.9, "strength": "weak", "test_count": 2, "distance_pct": 0.1},
        {"price": 99.0, "strength": "strong", "test_count": 9, "distance_pct": 0.25},
        {"price": 90.0, "strength": "strong", "test_count": 9, "distance_pct": 10.0},
    ], "resistance_levels": []}
    params = {"side": "support", "event": "approach", "proximity_pct": 0.3, "min_strength": "medium"}
    cands = liquidity_candidates(params, levels, [100.0, 100.0])
    assert [c.strength for c in cands] == ["weak", "strong"]
    assert first_passing("liquidity", params, cands).identity == "support:approach:99"
    assert first_passing("liquidity", {**params, "min_strength": "weak"}, cands).identity == "support:approach:99.9"


def test_sequence_candidates_are_the_single_match_or_nothing():
    flat = [{"time": i * 60_000, "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "volume": 1.0}
            for i in range(30)]
    params = {"steps": [{"type": "candle", "shape": "hammer"}], "within_bars": 3}
    assert sequence_candidates(params, flat) == []
    assert first_passing("sequence", params, []) is None


def test_first_passing_returns_the_first_sequence_candidate():
    c = Candidate("seq:1", "neutral", False, {})
    assert first_passing("sequence", {}, [c]) is c
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_rule_decision.py -q`
Expected: collection error `ImportError: cannot import name 'Candidate'`.

- [ ] **Step 3: Append to `backend/services/rule_decision.py`**

Add to its imports: `from datetime import timezone`, `from typing import List, Sequence, Tuple` (merge with the existing `typing` import), and:

```python
from analysis.candles import SHAPE_BIAS
from analysis.patterns_big import PATTERN_BIAS
from analysis.sequence import describe_steps, match_sequence
from models.rule_schemas import STRENGTH_ORDER
```

Then append:

```python
# --- candidates --------------------------------------------------------------
#
# Every matcher is "list what could match, then take the first that passes the
# filter". Split that way, a backtest can record the candidates once and try
# many filter values without re-running the detectors, and the live engine
# still gets exactly the answer the single-pass matcher gave.


@dataclass(frozen=True)
class Candidate:
    identity: str
    direction: str
    provisional: bool
    evidence: Dict[str, Any]
    confidence: Optional[float] = None
    strength: Optional[str] = None


def candle_time(candle: Dict[str, Any]) -> datetime:
    return datetime.fromtimestamp(int(candle["time"]) / 1000, tz=timezone.utc)


def strong_enough(strength: Optional[str], minimum: str) -> bool:
    try:
        return STRENGTH_ORDER.index(strength) >= STRENGTH_ORDER.index(minimum)
    except ValueError:
        return False


def pattern_identity(pattern: Dict[str, Any]) -> str:
    """
    Identity from the pattern's pivot times.

    Point keys differ by kind (low1/peak/low2 versus high1/trough/high2), so
    read the times out of the values and sort rather than naming the keys.
    """
    times = sorted(int(p["time"]) for p in pattern["points"].values())
    stamp = ":".join(str(t) for t in times)
    return f"{pattern['kind']}:{stamp}:{pattern['state']}"


def pattern_candidates(params: Dict[str, Any], patterns: Sequence[Dict[str, Any]]) -> List[Candidate]:
    kinds = set(params.get("kinds") or ())
    states = set(params.get("states") or ())
    # The detector already orders most actionable first; keep that order.
    return [
        Candidate(
            identity=pattern_identity(p),
            direction=PATTERN_BIAS.get(p["kind"], "neutral"),
            provisional=p["state"] != "confirmed",
            evidence=p,
            confidence=float(p["confidence"]),
        )
        for p in patterns
        if p["kind"] in kinds and p["state"] in states
    ]


def liquidity_candidates(
    params: Dict[str, Any],
    levels: Dict[str, Any],
    closes: Sequence[float],
) -> List[Candidate]:
    side = params.get("side", "support")
    event = params.get("event", "approach")
    proximity = float(params.get("proximity_pct", 0.3))

    if event == "approach":
        key = "support_levels" if side == "support" else "resistance_levels"
        # Approaching support is a potential bounce; resistance a rejection.
        direction = "bullish" if side == "support" else "bearish"
        return [
            Candidate(
                identity=f"{side}:approach:{level['price']:.8g}",
                direction=direction,
                provisional=False,
                evidence=level,
                strength=level["strength"],
            )
            for level in levels.get(key, [])
            if level["distance_pct"] <= proximity
        ]

    if len(closes) < 2:
        return []
    previous, last = closes[-2], closes[-1]

    # A break has to be searched across both lists: detect_levels classifies a
    # level against the latest close, so the moment price closes through a
    # support it is reported as resistance. The crossing decides, not the label.
    out: List[Candidate] = []
    for level in list(levels.get("support_levels", [])) + list(levels.get("resistance_levels", [])):
        price = float(level["price"])
        if side == "support" and previous > price >= last:
            out.append(Candidate(f"support:break:{price:.8g}", "bearish", False, level, strength=level["strength"]))
        elif side == "resistance" and previous < price <= last:
            out.append(Candidate(f"resistance:break:{price:.8g}", "bullish", False, level, strength=level["strength"]))
    return out


def sequence_candidates(params: Dict[str, Any], candles: Sequence[Dict[str, Any]]) -> List[Candidate]:
    """
    Identity is the bar time of every matched step. Direction comes from the
    final step: a cross above reads bullish, below bearish, a structure step
    its side, a lone candle its shape's bias. Never provisional.
    """
    steps = params.get("steps") or []
    picked = match_sequence(candles, steps, int(params.get("within_bars", 3)))
    if picked is None:
        return []

    times = [int(candles[i]["time"]) for i in picked]
    last = steps[-1]
    if last.get("type") == "indicator":
        direction = "bullish" if last.get("cross") == "above" else "bearish"
    elif last.get("type") == "structure":
        direction = last.get("side", "neutral")
    else:
        direction = SHAPE_BIAS.get(last.get("shape", ""), "neutral")

    evidence = {
        "summary": describe_steps(steps),
        "steps": [
            {**step, "bar_time": candle_time(candles[i]).isoformat()}
            for step, i in zip(steps, picked)
        ],
    }
    return [Candidate("seq:" + ":".join(str(t) for t in times), direction, False, evidence)]


def first_passing(agent: str, params: Dict[str, Any], candidates: Sequence[Candidate]) -> Optional[Candidate]:
    if agent == "pattern":
        floor = float(params.get("min_confidence", 0))
        return next((c for c in candidates if (c.confidence or 0) >= floor), None)
    if agent == "liquidity":
        minimum = params.get("min_strength", "medium")
        return next((c for c in candidates if strong_enough(c.strength, minimum)), None)
    return candidates[0] if candidates else None


def as_match(candidate: Optional[Candidate]) -> Optional[Tuple[str, str, bool, Dict[str, Any]]]:
    if candidate is None:
        return None
    return candidate.identity, candidate.direction, candidate.provisional, candidate.evidence
```

- [ ] **Step 4: Make `rule_engine.py` delegate**

Replace the import block at the top of `backend/services/rule_engine.py` (lines 14–26, before the `from services.rule_decision import (` block added in Task 1) with:

```python
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from analysis.levels import detect_levels
from analysis.patterns_big import detect_all_patterns
from repositories.rule_repository import RuleEventRepository, RuleRepository
from services.actions import ACTIONS
from services.candle_service import CandleService, CandleFetchError, UnknownTimeframe
```

Extend the Task 1 `from services.rule_decision import (...)` list with `as_match, candle_time, first_passing, liquidity_candidates, pattern_candidates, pattern_identity, sequence_candidates, strong_enough`.

Replace the functions `_candle_time`, `_strong_enough`, `_pattern_identity`, `_match_pattern`, `_match_liquidity`, `_match_sequence` (from `def _candle_time` down to the end of `_match_sequence`, just before `class RuleEngine:`) with:

```python
# Kept under their old names: callers and tests import these.
_candle_time = candle_time
_strong_enough = strong_enough
_pattern_identity = pattern_identity


def _match_pattern(params, patterns):
    return as_match(first_passing("pattern", params, pattern_candidates(params, patterns)))


def _match_liquidity(params, levels, closes):
    return as_match(first_passing("liquidity", params, liquidity_candidates(params, levels, closes)))


def _match_sequence(params, candles):
    return as_match(first_passing("sequence", params, sequence_candidates(params, candles)))
```

- [ ] **Step 5: Run the whole backend suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: **346 passed** (334 + 12), and `git diff --stat backend/tests/test_rule_engine.py` empty.

- [ ] **Step 6: Commit**

```bash
git add backend/services/rule_decision.py backend/services/rule_engine.py backend/tests/test_rule_decision.py
git commit -m "Split every rule matcher into candidates and a filter

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Job and tape tables and their repository

**Files:**
- Create: `backend/db/migrations/005_backtests.sql`, `backend/repositories/backtest_repository.py`
- Test: `backend/tests/test_migrations.py` (append), `backend/tests/test_backtest_repository.py`

**Interfaces:**
- Produces (`class BacktestRepository`, all `@staticmethod async` unless noted):
  - `create(owner_key: str, request: Dict) -> Dict` (`id, status, created_at`)
  - `count_active(owner_key: str) -> int`
  - `get_for_owner(job_id: str, owner_key: str) -> Optional[Dict]` (all columns)
  - `list_for_owner(owner_key: str, limit: int = 20) -> List[Dict]` (no `report`)
  - `cancel_or_delete(job_id: str, owner_key: str) -> Optional[str]` → `"cancelled"`, `"deleted"` or `None`
  - `claim_next() -> Optional[Dict]` (sets `replaying`, `started_at`, `progress 0`)
  - `requeue_running() -> int`
  - `status_of(job_id: str) -> Optional[str]`
  - `set_progress(job_id: str, status: str, progress: float) -> None` (never overwrites `cancelled`)
  - `finish(job_id: str, report: Dict) -> None`, `fail(job_id: str, error: str) -> None` (neither overwrites `cancelled`)
  - `get_tape(key: str) -> Optional[List]`, `put_tape(key: str, bars: int, rows: List) -> None`, `evict_tapes(older_than_days: int = 14) -> None`
  - module functions `encode_tape(rows: List) -> bytes`, `decode_tape(blob: bytes) -> List`
  - `ACTIVE_STATUSES = ("queued", "replaying", "studying", "tuning")`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_migrations.py`:

```python
def test_backtests_migration_is_idempotent_and_allows_every_status():
    sql = (MIGRATIONS / "005_backtests.sql").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS backtest_jobs" in sql
    assert "CREATE TABLE IF NOT EXISTS signal_tapes" in sql
    assert sql.count("CREATE INDEX IF NOT EXISTS") == 2
    for status in ("queued", "replaying", "studying", "tuning", "done", "failed", "cancelled"):
        assert f"'{status}'" in sql
```

`backend/tests/test_backtest_repository.py`:

```python
"""Tape codec: compact, lossless, and small enough to store."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from repositories.backtest_repository import ACTIVE_STATUSES, decode_tape, encode_tape


def test_tape_round_trips_exactly():
    rows = [[405, [["W:1:2:3:confirmed", "bullish", False, 71.5, None]]],
            [406, [["support:approach:99.5", "bullish", False, None, "strong"]]]]
    assert decode_tape(encode_tape(rows)) == rows


def test_tape_compresses_repetitive_rows():
    rows = [[i, [["W:1700000000000:1700003600000:1700007200000:confirmed", "bullish", False, 70.0, None]]]
            for i in range(20_000)]
    assert len(encode_tape(rows)) < 200_000


def test_active_statuses_are_the_running_ones():
    assert ACTIVE_STATUSES == ("queued", "replaying", "studying", "tuning")
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_migrations.py tests/test_backtest_repository.py -q`
Expected: `FileNotFoundError` for `005_backtests.sql` and an import error for `backtest_repository`.

- [ ] **Step 3: Write the migration**

`backend/db/migrations/005_backtests.sql`:

```sql
-- Backtest jobs and the cached candidate tapes they replay into.
--
-- Applied idempotently at startup by Database.bootstrap_schema(). 'tuning' is
-- allowed now though slice 4 is the first to use it, so the CHECK never has to
-- be dropped and recreated on a live table.
CREATE TABLE IF NOT EXISTS backtest_jobs (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_key    TEXT        NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at   TIMESTAMPTZ,
    finished_at  TIMESTAMPTZ,
    status       TEXT        NOT NULL DEFAULT 'queued'
                 CHECK (status IN ('queued', 'replaying', 'studying', 'tuning', 'done', 'failed', 'cancelled')),
    progress     REAL        NOT NULL DEFAULT 0,
    request      JSONB       NOT NULL,
    report       JSONB,
    error        TEXT
);

CREATE INDEX IF NOT EXISTS backtest_jobs_owner_created
    ON backtest_jobs (owner_key, created_at DESC);

CREATE INDEX IF NOT EXISTS backtest_jobs_queue
    ON backtest_jobs (created_at) WHERE status = 'queued';

-- gzip-compressed JSON rows: [bar_index, [[identity, direction, provisional, confidence, strength], ...]]
CREATE TABLE IF NOT EXISTS signal_tapes (
    key         TEXT        PRIMARY KEY,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    bars        INTEGER     NOT NULL,
    rows        BYTEA       NOT NULL
);
```

- [ ] **Step 4: Write the repository**

`backend/repositories/backtest_repository.py`:

```python
"""
Backtest jobs and candidate tapes.

Owner-facing reads filter on owner_key and return nothing on a mismatch, like
the rule repository, so a job id cannot be probed across wallets. Writes from
the worker never overwrite 'cancelled': the API can cancel at any moment and
the worker only notices between chunks.
"""
import gzip
import json
from typing import Any, Dict, List, Optional

from models.database import db

ACTIVE_STATUSES = ("queued", "replaying", "studying", "tuning")

JOB_COLUMNS = """
    id, owner_key, created_at, started_at, finished_at, status, progress,
    request, report, error
"""
SUMMARY_COLUMNS = """
    id, created_at, started_at, finished_at, status, progress, request, error
"""


def encode_tape(rows: List[Any]) -> bytes:
    return gzip.compress(json.dumps(rows, separators=(",", ":")).encode("utf-8"), compresslevel=6)


def decode_tape(blob: bytes) -> List[Any]:
    return json.loads(gzip.decompress(bytes(blob)).decode("utf-8"))


class BacktestRepository:
    @staticmethod
    async def create(owner_key: str, request: Dict[str, Any]) -> Dict[str, Any]:
        return await db.fetchrow(
            "INSERT INTO backtest_jobs (owner_key, request) VALUES ($1, $2) "
            "RETURNING id, status, created_at",
            owner_key,
            request,
        )

    @staticmethod
    async def count_active(owner_key: str) -> int:
        row = await db.fetchrow(
            "SELECT count(*) AS n FROM backtest_jobs WHERE owner_key = $1 AND status = ANY($2::text[])",
            owner_key,
            list(ACTIVE_STATUSES),
        )
        return int(row["n"])

    @staticmethod
    async def get_for_owner(job_id: str, owner_key: str) -> Optional[Dict[str, Any]]:
        return await db.fetchrow(
            f"SELECT {JOB_COLUMNS} FROM backtest_jobs WHERE id = $1 AND owner_key = $2",
            job_id,
            owner_key,
        )

    @staticmethod
    async def list_for_owner(owner_key: str, limit: int = 20) -> List[Dict[str, Any]]:
        return await db.fetch(
            f"SELECT {SUMMARY_COLUMNS} FROM backtest_jobs WHERE owner_key = $1 "
            "ORDER BY created_at DESC LIMIT $2",
            owner_key,
            limit,
        )

    @staticmethod
    async def cancel_or_delete(job_id: str, owner_key: str) -> Optional[str]:
        cancelled = await db.fetchrow(
            "UPDATE backtest_jobs SET status = 'cancelled', finished_at = NOW() "
            "WHERE id = $1 AND owner_key = $2 AND status = ANY($3::text[]) RETURNING id",
            job_id,
            owner_key,
            list(ACTIVE_STATUSES),
        )
        if cancelled:
            return "cancelled"
        deleted = await db.fetchrow(
            "DELETE FROM backtest_jobs WHERE id = $1 AND owner_key = $2 RETURNING id",
            job_id,
            owner_key,
        )
        return "deleted" if deleted else None

    @staticmethod
    async def claim_next() -> Optional[Dict[str, Any]]:
        return await db.fetchrow(
            f"""
            UPDATE backtest_jobs
            SET status = 'replaying', started_at = NOW(), progress = 0
            WHERE id = (
                SELECT id FROM backtest_jobs WHERE status = 'queued'
                ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1
            )
            RETURNING {JOB_COLUMNS}
            """
        )

    @staticmethod
    async def requeue_running() -> int:
        rows = await db.fetch(
            "UPDATE backtest_jobs SET status = 'queued', progress = 0 "
            "WHERE status IN ('replaying', 'studying', 'tuning') RETURNING id"
        )
        return len(rows)

    @staticmethod
    async def status_of(job_id: str) -> Optional[str]:
        row = await db.fetchrow("SELECT status FROM backtest_jobs WHERE id = $1", job_id)
        return row["status"] if row else None

    @staticmethod
    async def set_progress(job_id: str, status: str, progress: float) -> None:
        await db.execute(
            "UPDATE backtest_jobs SET status = $2, progress = $3 WHERE id = $1 AND status <> 'cancelled'",
            job_id,
            status,
            progress,
        )

    @staticmethod
    async def finish(job_id: str, report: Dict[str, Any]) -> None:
        await db.execute(
            "UPDATE backtest_jobs SET status = 'done', progress = 1, report = $2, finished_at = NOW() "
            "WHERE id = $1 AND status <> 'cancelled'",
            job_id,
            report,
        )

    @staticmethod
    async def fail(job_id: str, error: str) -> None:
        await db.execute(
            "UPDATE backtest_jobs SET status = 'failed', error = $2, finished_at = NOW() "
            "WHERE id = $1 AND status <> 'cancelled'",
            job_id,
            error,
        )

    @staticmethod
    async def get_tape(key: str) -> Optional[List[Any]]:
        row = await db.fetchrow("SELECT rows FROM signal_tapes WHERE key = $1", key)
        return decode_tape(row["rows"]) if row else None

    @staticmethod
    async def put_tape(key: str, bars: int, rows: List[Any]) -> None:
        await db.execute(
            "INSERT INTO signal_tapes (key, bars, rows) VALUES ($1, $2, $3) "
            "ON CONFLICT (key) DO UPDATE SET rows = EXCLUDED.rows, bars = EXCLUDED.bars, created_at = NOW()",
            key,
            bars,
            encode_tape(rows),
        )

    @staticmethod
    async def evict_tapes(older_than_days: int = 14) -> None:
        await db.execute(
            "DELETE FROM signal_tapes WHERE created_at < NOW() - make_interval(days => $1)",
            older_than_days,
        )
```

- [ ] **Step 5: Run tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_migrations.py tests/test_backtest_repository.py -q`
Expected: 6 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/db/migrations/005_backtests.sql backend/repositories/backtest_repository.py backend/tests/test_migrations.py backend/tests/test_backtest_repository.py
git commit -m "Tables and repository for backtest jobs and cached tapes

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: The backtest request schema

**Files:**
- Create: `backend/models/backtest_schemas.py`
- Test: `backend/tests/test_backtest_schemas.py`

**Interfaces:**
- Consumes: `models.rule_schemas.RuleCreate`, `services.history_service.HISTORY_DEPTH_DAYS`.
- Produces: `BACKTEST_TIMEFRAMES: Tuple[str, ...]`, `MIN_EVALUATED_BARS = 300`, `window_size(lookback: int) -> int` (= `lookback - 1`), `required_bars(lookback: int) -> int`, `class BacktestCreate(BaseModel)` with `rule: RuleCreate`, `neutral: Literal["skip","long","short"] = "skip"`, `split: float = 0.7` (0.5–0.9).

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_backtest_schemas.py`:

```python
"""What a backtest request may be."""
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from models.backtest_schemas import (
    BACKTEST_TIMEFRAMES,
    MIN_EVALUATED_BARS,
    BacktestCreate,
    required_bars,
    window_size,
)

RULE = {
    "name": "doji", "symbol": "btcusdt", "timeframe": "1h",
    "params": {"agent": "sequence", "steps": [{"type": "candle", "shape": "doji"}]},
}


def test_defaults():
    body = BacktestCreate(rule=RULE)
    assert body.neutral == "skip" and body.split == 0.7
    assert body.rule.params.lookback == 300


def test_window_matches_the_live_sweep():
    assert window_size(300) == 299
    assert required_bars(300) == 299 + MIN_EVALUATED_BARS


def test_timeframes_are_the_ones_with_history():
    assert BACKTEST_TIMEFRAMES == ("5m", "15m", "1h", "1d")
    with pytest.raises(ValidationError, match="5m, 15m, 1h or 1d"):
        BacktestCreate(rule={**RULE, "timeframe": "1m"})


@pytest.mark.parametrize("split", [0.4, 0.95])
def test_split_is_bounded(split):
    with pytest.raises(ValidationError):
        BacktestCreate(rule=RULE, split=split)


def test_an_invalid_rule_is_rejected_by_the_rule_schema():
    with pytest.raises(ValidationError):
        BacktestCreate(rule={**RULE, "params": {"agent": "sequence", "steps": []}})
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_backtest_schemas.py -q`
Expected: `ModuleNotFoundError: No module named 'models.backtest_schemas'`.

- [ ] **Step 3: Implement**

`backend/models/backtest_schemas.py`:

```python
"""
What a backtest request may be.

The rule is a RuleCreate - the same schema that arms a rule - so anything the
Strategy panel or the chat can draft can be backtested, and nothing else can.
"""
from typing import Literal, Tuple

from pydantic import BaseModel, Field, model_validator

from models.rule_schemas import RuleCreate
from services.history_service import HISTORY_DEPTH_DAYS

BACKTEST_TIMEFRAMES: Tuple[str, ...] = tuple(HISTORY_DEPTH_DAYS)

# Bars that must remain after the warm-up window, so both the seen and the
# unseen slice hold enough bars to say anything.
MIN_EVALUATED_BARS = 300


def window_size(lookback: int) -> int:
    """Closed bars the live sweep hands a rule: `lookback` fetched, the forming one dropped."""
    return lookback - 1


def required_bars(lookback: int) -> int:
    return window_size(lookback) + MIN_EVALUATED_BARS


class BacktestCreate(BaseModel):
    rule: RuleCreate
    # Signals with no direction of their own (doji, inside bar): skipped, or
    # read as long or short.
    neutral: Literal["skip", "long", "short"] = "skip"
    # Fraction of evaluated bars that are "seen"; the rest are unseen.
    split: float = Field(default=0.7, ge=0.5, le=0.9)

    @model_validator(mode="after")
    def _timeframe_has_history(self) -> "BacktestCreate":
        if self.rule.timeframe not in BACKTEST_TIMEFRAMES:
            raise ValueError("Backtests run on 5m, 15m, 1h or 1d")
        return self
```

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_backtest_schemas.py -q`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/models/backtest_schemas.py backend/tests/test_backtest_schemas.py
git commit -m "Backtest request schema built on RuleCreate

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: Replay into a candidate tape

**Files:**
- Create: `backend/backtest/__init__.py` (empty), `backend/backtest/replay.py`, `backend/tests/walks.py`
- Test: `backend/tests/test_backtest_replay.py`

**Interfaces:**
- Consumes: `rule_decision.pattern_candidates/liquidity_candidates/sequence_candidates/first_passing`, `detect_all_patterns`, `detect_levels`, `window_size`.
- Produces:
  - `TAPE_VERSION = 1`, `FILTER_KEYS: Dict[str, Tuple[str, ...]]`
  - `detector_params(params: Dict) -> Dict`
  - `tape_key(symbol: str, timeframe: str, params: Dict, last_time_ms: int) -> str`
  - `first_index(params: Dict) -> int` (= `window_size(lookback) - 1`)
  - `candidates_at(candles: List[Dict], i: int, params: Dict) -> List[Candidate]`
  - `replay_range(candles: List[Dict], params: Dict, start: int, end: int) -> List[list]` — rows `[i, [[identity, direction, provisional, confidence, strength], ...]]`, only bars with candidates.
- `tests/walks.py`: `H`, `T0`, `random_walk(n, seed=1, step_ms=H, vol=0.006) -> List[Dict]`, `doji_series(n, every=5, step_ms=H) -> List[Dict]`.

- [ ] **Step 1: Write the shared fixtures**

`backend/tests/walks.py`:

```python
"""Deterministic candle series for backtest tests."""
from typing import Dict, List

import numpy as np

H = 3_600_000
T0 = 1_700_000_000_000 - (1_700_000_000_000 % H)


def random_walk(n: int, seed: int = 1, step_ms: int = H, vol: float = 0.006) -> List[Dict]:
    rng = np.random.default_rng(seed)
    closes = 60_000.0 * np.exp(np.cumsum(rng.normal(0, vol, n)))
    out, prev = [], float(closes[0])
    for i, close in enumerate(closes):
        o, c = prev, float(close)
        hi = max(o, c) * (1 + abs(rng.normal(0, vol / 3)))
        lo = min(o, c) * (1 - abs(rng.normal(0, vol / 3)))
        out.append({"time": T0 + i * step_ms, "open": o, "high": hi, "low": lo, "close": c, "volume": 1.0})
        prev = c
    return out


def doji_series(n: int, every: int = 5, step_ms: int = H) -> List[Dict]:
    """Wide trending bars, with a textbook doji every `every` bars."""
    out, price = [], 100.0
    for i in range(n):
        if i % every == every - 1:
            o = c = price
            hi, lo = price + 2.0, price - 2.0
        else:
            o, c = price, price + 1.0
            hi, lo = c + 0.2, o - 0.2
            price = c
        out.append({"time": T0 + i * step_ms, "open": o, "high": hi, "low": lo, "close": c, "volume": 1.0})
    return out
```

- [ ] **Step 2: Write the failing tests**

`backend/tests/test_backtest_replay.py`:

```python
"""Replay: no look-ahead, and the same answer the live engine gives."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backtest.replay import candidates_at, first_index, replay_range, tape_key
from models.rule_schemas import RuleCreate
from repositories.rule_repository import RuleEventRepository
from services.rule_decision import first_passing
from services.rule_engine import RuleEngine
from walks import H, doji_series, random_walk


def params_for(raw):
    return RuleCreate(name="t", symbol="BTCUSDT", timeframe="1h", params=raw).params.model_dump()


DOJI = params_for({"agent": "sequence", "steps": [{"type": "candle", "shape": "doji"}], "lookback": 60})
W = params_for({"agent": "pattern", "kinds": ["W", "M"], "states": ["forming", "approaching", "confirmed"],
                "min_confidence": 0, "lookback": 150})
NEAR_SUPPORT = params_for({"agent": "liquidity", "side": "support", "event": "approach",
                           "proximity_pct": 2.0, "min_strength": "weak", "lookback": 150})


@pytest.fixture(autouse=True)
def no_dedup_lookup(monkeypatch):
    async def never(_key):
        return False
    monkeypatch.setattr(RuleEventRepository, "exists", never)


def test_first_index_leaves_a_full_live_window():
    assert first_index(DOJI) == 58  # window of 59 bars ends at index 58


def test_doji_rule_finds_every_doji_after_warmup():
    candles = doji_series(200)
    rows = replay_range(candles, DOJI, first_index(DOJI), len(candles))
    assert [r[0] for r in rows] == [i for i in range(first_index(DOJI), 200) if i % 5 == 4]
    assert rows[0][1][0][1] == "neutral"


@pytest.mark.parametrize("params", [DOJI, W, NEAR_SUPPORT], ids=["sequence", "pattern", "liquidity"])
def test_no_look_ahead(params):
    candles = random_walk(260, seed=3) if params is not DOJI else doji_series(260)
    start = first_index(params)
    before = replay_range(candles, params, start, 230)
    future = [{**c, "time": c["time"] + 1000 * H, "high": c["high"] * 3, "low": c["low"] / 3}
              for c in random_walk(30, seed=99)]
    after = replay_range(candles[:230] + future, params, start, 230)
    assert before == after


@pytest.mark.parametrize("params", [DOJI, W, NEAR_SUPPORT], ids=["sequence", "pattern", "liquidity"])
async def test_parity_with_the_live_engine(params):
    candles = random_walk(260, seed=5) if params is not DOJI else doji_series(260)
    size = params["lookback"] - 1
    rule = {"id": "r", "owner_key": "o", "agent": params["agent"], "symbol": "BTCUSDT", "timeframe": "1h",
            "params": params, "persist_bars": 0, "cooldown_secs": 0, "pending": None,
            "last_candle_time": None, "last_fired_at": None}
    for i in range(first_index(params), 260, 7):
        window = candles[i + 1 - size: i + 1]
        live, _ = await RuleEngine.evaluate_rule(rule, window, dry_run=True)
        replayed = first_passing(params["agent"], params, candidates_at(candles, i, params))
        assert (live.identity if live else None) == (replayed.identity if replayed else None), i


def test_tape_key_ignores_filters_but_not_detector_settings():
    base = tape_key("BTCUSDT", "1h", W, 123)
    assert tape_key("btcusdt", "1h", {**W, "min_confidence": 80}, 123) == base
    assert tape_key("BTCUSDT", "1h", {**W, "strictness": "strict"}, 123) != base
    assert tape_key("BTCUSDT", "1h", {**W, "lookback": 200}, 123) != base
    assert tape_key("BTCUSDT", "1h", W, 124) != base
    assert tape_key("BTCUSDT", "1h", {**NEAR_SUPPORT, "proximity_pct": 1.0}, 123) != tape_key("BTCUSDT", "1h", NEAR_SUPPORT, 123)
```

- [ ] **Step 3: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_backtest_replay.py -q`
Expected: `ModuleNotFoundError: No module named 'backtest'`.

- [ ] **Step 4: Implement**

`backend/backtest/__init__.py`: empty.

`backend/backtest/replay.py`:

```python
"""
Replay history through a rule's detectors, one closed bar at a time.

At bar i the detectors see exactly the window the live sweep would have handed
them at that bar's close - never a later bar. What is recorded is every
candidate before filtering, so filter values can be tried later without
running the detectors again. Pure and synchronous: the runner calls it in a
worker thread, a chunk at a time.
"""
import hashlib
import json
from typing import Any, Dict, List, Tuple

from analysis.levels import detect_levels
from analysis.patterns_big import detect_all_patterns
from models.backtest_schemas import window_size
from services.rule_decision import (
    Candidate,
    liquidity_candidates,
    pattern_candidates,
    sequence_candidates,
)

# Bump when the tape format or any detector changes meaning, so stale cached
# tapes are never read.
TAPE_VERSION = 1

# Applied to candidates after replay, so not part of what a tape depends on.
FILTER_KEYS: Dict[str, Tuple[str, ...]] = {
    "pattern": ("min_confidence",),
    "liquidity": ("min_strength",),
    "sequence": (),
}


def detector_params(params: Dict[str, Any]) -> Dict[str, Any]:
    skip = FILTER_KEYS[params["agent"]]
    return {k: v for k, v in params.items() if k not in skip}


def tape_key(symbol: str, timeframe: str, params: Dict[str, Any], last_time_ms: int) -> str:
    payload = json.dumps(
        {
            "v": TAPE_VERSION,
            "symbol": symbol.upper(),
            "timeframe": timeframe,
            "params": detector_params(params),
            "last": int(last_time_ms),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def first_index(params: Dict[str, Any]) -> int:
    return window_size(int(params["lookback"])) - 1


def candidates_at(candles: List[Dict[str, Any]], i: int, params: Dict[str, Any]) -> List[Candidate]:
    window = candles[max(0, i + 1 - window_size(int(params["lookback"]))): i + 1]
    agent = params["agent"]
    if agent == "pattern":
        patterns = detect_all_patterns(
            window,
            strictness=params.get("strictness", "balanced"),
            source=params.get("source", "wick"),
            scale=params.get("scale", "swing"),
            max_results=None,
        )
        return pattern_candidates(params, patterns)
    if agent == "liquidity":
        return liquidity_candidates(params, detect_levels(window), [float(c["close"]) for c in window])
    if agent == "sequence":
        return sequence_candidates(params, window)
    raise ValueError(f"Cannot replay agent '{agent}'")


def replay_range(candles: List[Dict[str, Any]], params: Dict[str, Any], start: int, end: int) -> List[list]:
    rows: List[list] = []
    for i in range(start, end):
        found = candidates_at(candles, i, params)
        if found:
            rows.append([i, [[c.identity, c.direction, c.provisional, c.confidence, c.strength] for c in found]])
    return rows
```

- [ ] **Step 5: Run tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_backtest_replay.py -q`
Expected: 9 passed (pattern cases take a few seconds). If `test_doji_rule_finds_every_doji_after_warmup` reports extra indices, print `rows` and check `analysis.candles` doji thresholds against `doji_series` bars — adjust **the fixture** so its non-doji bars are unambiguous, never the detector.

- [ ] **Step 6: Commit**

```bash
git add backend/backtest/__init__.py backend/backtest/replay.py backend/tests/walks.py backend/tests/test_backtest_replay.py
git commit -m "Replay history into a candidate tape, with no look-ahead and live parity

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: Signals from the tape

**Files:**
- Create: `backend/backtest/signals.py`
- Test: `backend/tests/test_backtest_signals.py`

**Interfaces:**
- Consumes: `Candidate`, `FiringState`, `decide`, `first_passing`.
- Produces:
  - `@dataclass(frozen=True) TapeSignal(index: int, time: int, identity: str, direction: str, provisional: bool)`
  - `signals_from_tape(tape: List[list], candles: List[Dict], params: Dict, *, timeframe_ms: int, persist_bars: int, cooldown_secs: int, start: int, end: int) -> List[TapeSignal]`
  - `distinct_setups(signals: List[TapeSignal]) -> List[TapeSignal]`

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_backtest_signals.py`:

```python
"""Turning a tape into the fires the live engine would have produced."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backtest.signals import distinct_setups, signals_from_tape
from walks import H, T0


def bars(n):
    return [{"time": T0 + i * H, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0} for i in range(n)]


def row(i, *cands):
    return [i, [list(c) for c in cands]]


SEQ = {"agent": "sequence"}


def run(tape, params=SEQ, persist=0, cooldown=0, n=10):
    return signals_from_tape(tape, bars(n), params, timeframe_ms=H, persist_bars=persist,
                             cooldown_secs=cooldown, start=0, end=n)


def test_every_candidate_bar_fires_without_persistence_or_cooldown():
    tape = [row(2, ("a", "bullish", False, None, None)), row(3, ("b", "bearish", False, None, None))]
    assert [(s.index, s.identity, s.direction) for s in run(tape)] == [(2, "a", "bullish"), (3, "b", "bearish")]
    assert run(tape)[0].time == T0 + 2 * H


def test_persistence_delays_the_fire_by_a_bar():
    tape = [row(i, ("a", "bullish", False, None, None)) for i in (2, 3, 4)]
    assert [s.index for s in run(tape, persist=1)] == [3, 4]


def test_cooldown_runs_on_bar_close_times():
    tape = [row(i, ("a", "bullish", False, None, None)) for i in range(0, 6)]
    # Fired at bar 0 close (T0+1h). Bar 1 closes at T0+2h: 3600s < 7200s. Bar 2 at T0+3h: fires.
    assert [s.index for s in run(tape, cooldown=7200)] == [0, 2, 4]


def test_the_filter_picks_the_first_candidate_that_passes():
    params = {"agent": "pattern", "min_confidence": 70}
    tape = [row(1, ("weak", "bearish", False, 50.0, None), ("good", "bullish", False, 80.0, None))]
    assert [s.identity for s in run(tape, params)] == ["good"]
    assert run([row(1, ("weak", "bearish", False, 50.0, None))], params) == []


def test_distinct_setups_keep_the_first_fire_of_each():
    tape = [row(i, ("a", "bullish", False, None, None)) for i in (1, 2, 3)] + [row(5, ("b", "bearish", False, None, None))]
    assert [(s.index, s.identity) for s in distinct_setups(run(tape))] == [(1, "a"), (5, "b")]
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_backtest_signals.py -q`
Expected: `ModuleNotFoundError: No module named 'backtest.signals'`.

- [ ] **Step 3: Implement**

`backend/backtest/signals.py`:

```python
"""
From a candidate tape to fires, through the live engine's own decision.

Each bar's close is the clock: persistence counts closes and cooldown measures
from the close of the bar that fired. Filters are applied here, which is why
one tape serves every filter value a tuning run tries.
"""
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from services.rule_decision import Candidate, FiringState, decide, first_passing


@dataclass(frozen=True)
class TapeSignal:
    index: int
    time: int
    identity: str
    direction: str
    provisional: bool


def _candidates(row: list) -> List[Candidate]:
    return [
        Candidate(identity=c[0], direction=c[1], provisional=c[2], evidence={}, confidence=c[3], strength=c[4])
        for c in row[1]
    ]


def signals_from_tape(
    tape: List[list],
    candles: List[Dict[str, Any]],
    params: Dict[str, Any],
    *,
    timeframe_ms: int,
    persist_bars: int,
    cooldown_secs: int,
    start: int,
    end: int,
) -> List[TapeSignal]:
    by_index = {int(r[0]): r for r in tape}
    state = FiringState()
    out: List[TapeSignal] = []

    for i in range(start, end):
        tape_row = by_index.get(i)
        chosen = first_passing(params["agent"], params, _candidates(tape_row)) if tape_row else None
        opened = datetime.fromtimestamp(int(candles[i]["time"]) / 1000, tz=timezone.utc)
        closed = opened + timedelta(milliseconds=timeframe_ms)

        decision = decide(
            state,
            chosen.identity if chosen else None,
            opened,
            persist_bars=persist_bars,
            cooldown_secs=cooldown_secs,
            now=closed,
        )
        state = decision.state
        if chosen is not None and decision.blocked is None:
            out.append(TapeSignal(i, int(candles[i]["time"]), chosen.identity, chosen.direction, chosen.provisional))
            state = replace(state, last_fired_at=closed)

    return out


def distinct_setups(signals: List[TapeSignal]) -> List[TapeSignal]:
    """
    The first fire of each setup. A live rule re-fires on every bar its setup
    persists; those fires are one observation, and counting them as many would
    make a confidence interval look far tighter than the evidence allows.
    """
    seen = set()
    out = []
    for s in signals:
        if s.identity not in seen:
            seen.add(s.identity)
            out.append(s)
    return out
```

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_backtest_signals.py -q`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/backtest/signals.py backend/tests/test_backtest_signals.py
git commit -m "Derive fires from a tape with bar-close clocks

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 7: The signal study

**Files:**
- Create: `backend/backtest/study.py`
- Test: `backend/tests/test_backtest_study.py`

**Interfaces:**
- Consumes: `TapeSignal`, `analysis.patterns.atr`.
- Produces:
  - `HORIZONS = (1, 5, 10, 20)`, `HEADLINE_HORIZON = 10`, `EXCURSION_BARS = 20`, `BOOTSTRAP_SAMPLES = 2000`, `BOOTSTRAP_SEED = 7`, `MIN_SIGNALS = 30`
  - `signed(direction: str, neutral: str) -> Optional[int]`
  - `bootstrap_ci(values: np.ndarray, baseline: float) -> Tuple[float, float]`
  - `period_study(candles, signals, lo: int, hi: int, neutral: str) -> Dict`
  - `study(candles, signals, *, start: int, split: int, end: int, neutral: str) -> Dict` → `{"seen": ..., "unseen": ...}`
- Period dict: `{from, to, bars, signals, skipped_neutral, long_share, horizons: [{h, signals, mean_pct, baseline_pct, edge_pct, ci_pct: [lo, hi] | None, hit_rate, baseline_hit_rate}], mfe_atr, mae_atr, flags: [...]}`; flags ⊆ `{"too_few_signals", "no_edge_detected"}`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_backtest_study.py`:

```python
"""The signal study: arithmetic, the unseen boundary, the baseline, honesty."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backtest.signals import TapeSignal
from backtest.study import MIN_SIGNALS, period_study, signed, study
from walks import H, T0, random_walk


def trend(n, step=0.01):
    """Closes rising by `step` (1%) every bar."""
    out, price = [], 100.0
    for i in range(n):
        nxt = price * (1 + step)
        out.append({"time": T0 + i * H, "open": price, "high": nxt * 1.001, "low": price * 0.999, "close": nxt, "volume": 1.0})
        price = nxt
    return out


def sig(i, direction="bullish"):
    return TapeSignal(i, T0 + i * H, f"s{i}", direction, False)


def h(period, horizon):
    return next(x for x in period["horizons"] if x["h"] == horizon)


def test_signed_directions():
    assert signed("bullish", "skip") == 1 and signed("bearish", "skip") == -1
    assert signed("neutral", "skip") is None and signed("neutral", "short") == -1


def test_forward_return_is_signed_by_direction():
    candles = trend(100)
    up = period_study(candles, [sig(10)], 0, 100, "skip")
    down = period_study(candles, [sig(10, "bearish")], 0, 100, "skip")
    assert h(up, 1)["mean_pct"] == 1.0
    assert h(down, 1)["mean_pct"] == -1.0


def test_baseline_follows_the_direction_mix():
    candles = trend(100)
    shorts = period_study(candles, [sig(i, "bearish") for i in range(0, 60, 3)], 0, 100, "skip")
    assert h(shorts, 1)["baseline_pct"] == -1.0
    assert h(shorts, 1)["edge_pct"] == 0.0


def test_a_seen_horizon_never_reads_past_the_split():
    candles = trend(100)
    report = study(candles, [sig(45)], start=0, split=50, end=100, neutral="skip")
    assert h(report["seen"], 1)["signals"] == 1
    assert h(report["seen"], 10)["signals"] == 0
    assert report["unseen"]["signals"] == 0


def test_neutral_signals_are_skipped_or_directed():
    candles = trend(100)
    skipped = period_study(candles, [sig(5, "neutral")], 0, 100, "skip")
    longed = period_study(candles, [sig(5, "neutral")], 0, 100, "long")
    assert skipped["signals"] == 0 and skipped["skipped_neutral"] == 1
    assert longed["signals"] == 1


def test_excursions_are_in_atr_units():
    candles = trend(100)
    p = period_study(candles, [sig(30)], 0, 100, "skip")
    assert p["mfe_atr"] > 0 and p["mae_atr"] < p["mfe_atr"]


def test_confidence_interval_is_reproducible_and_brackets_the_edge():
    candles = random_walk(1500, seed=4)
    signals = [sig(i, "bullish" if i % 2 else "bearish") for i in range(20, 1400, 9)]
    a = period_study(candles, signals, 0, 1500, "skip")
    b = period_study(candles, signals, 0, 1500, "skip")
    assert a == b
    head = h(a, 10)
    assert head["ci_pct"][0] <= head["edge_pct"] <= head["ci_pct"][1]


def test_few_signals_are_flagged():
    p = period_study(trend(100), [sig(3)], 0, 100, "skip")
    assert "too_few_signals" in p["flags"] and p["signals"] < MIN_SIGNALS


def test_random_signals_on_random_walks_rarely_claim_an_edge():
    claimed = 0
    for seed in range(20):
        candles = random_walk(3000, seed=100 + seed)
        rng = np.random.default_rng(seed)
        signals = [sig(i, "bullish" if rng.random() < 0.5 else "bearish") for i in range(30, 2900, 23)]
        if "no_edge_detected" not in period_study(candles, signals, 0, 3000, "skip")["flags"]:
            claimed += 1
    # A 95% interval should wrongly exclude zero about once in twenty.
    assert claimed <= 3


def test_nothing_non_finite_reaches_the_report():
    p = period_study(trend(30), [], 0, 30, "skip")
    assert p["signals"] == 0 and h(p, 10)["mean_pct"] is None and h(p, 10)["ci_pct"] is None
    assert "no_edge_detected" in p["flags"]
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_backtest_study.py -q`
Expected: `ModuleNotFoundError: No module named 'backtest.study'`.

- [ ] **Step 3: Implement**

`backend/backtest/study.py`:

```python
"""
Does the signal predict anything?

For each signal: the return over the next 1, 5, 10 and 20 bars in the
signal's direction, and how far price went for and against it. Compared with
the same measurement over every bar in the period, taken in the same mix of
longs and shorts - a bullish signal in a bull market has to beat the bull
market, not zero. The edge carries a bootstrap confidence interval, so "no edge"
is an answer the report can give plainly.

Seen and unseen are studied separately, and no seen measurement reads a price
from the unseen slice.
"""
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from analysis.patterns import atr
from backtest.signals import TapeSignal

HORIZONS = (1, 5, 10, 20)
HEADLINE_HORIZON = 10
EXCURSION_BARS = 20
BOOTSTRAP_SAMPLES = 2000
BOOTSTRAP_SEED = 7
MIN_SIGNALS = 30
ATR_BARS = 15  # ATR(14) needs 15 bars


def _r(value: Optional[float], places: int = 4) -> Optional[float]:
    if value is None:
        return None
    value = float(value)
    return round(value, places) if math.isfinite(value) else None


def signed(direction: str, neutral: str) -> Optional[int]:
    if direction == "bullish":
        return 1
    if direction == "bearish":
        return -1
    return {"long": 1, "short": -1}.get(neutral)


def bootstrap_ci(values: np.ndarray, baseline: float) -> Tuple[float, float]:
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    picks = rng.integers(0, values.size, size=(BOOTSTRAP_SAMPLES, values.size))
    edges = values[picks].mean(axis=1) - baseline
    return float(np.percentile(edges, 2.5)), float(np.percentile(edges, 97.5))


def period_study(
    candles: Sequence[Dict[str, Any]],
    signals: Sequence[TapeSignal],
    lo: int,
    hi: int,
    neutral: str,
) -> Dict[str, Any]:
    closes = np.array([float(c["close"]) for c in candles], dtype=float)
    highs = np.array([float(c["high"]) for c in candles], dtype=float)
    lows = np.array([float(c["low"]) for c in candles], dtype=float)

    in_period = [s for s in signals if lo <= s.index < hi]
    directed = [(s.index, signed(s.direction, neutral)) for s in in_period]
    usable = [(i, d) for i, d in directed if d is not None]
    skipped = len(directed) - len(usable)
    long_share = float(np.mean([d == 1 for _, d in usable])) if usable else 0.5

    horizons: List[Dict[str, Any]] = []
    for h in HORIZONS:
        values = np.array([d * (closes[i + h] / closes[i] - 1) for i, d in usable if i + h < hi], dtype=float)
        idx = np.arange(lo, max(lo, hi - h))
        market = closes[idx + h] / closes[idx] - 1 if idx.size else np.array([], dtype=float)

        baseline = (2 * long_share - 1) * float(market.mean()) if market.size else None
        base_hit = (
            long_share * float((market > 0).mean()) + (1 - long_share) * float((market < 0).mean())
            if market.size else None
        )
        mean = float(values.mean()) if values.size else None
        edge = mean - baseline if mean is not None and baseline is not None else None
        ci = bootstrap_ci(values, baseline) if values.size >= 2 and baseline is not None else None

        horizons.append({
            "h": h,
            "signals": int(values.size),
            "mean_pct": _r(mean * 100) if mean is not None else None,
            "baseline_pct": _r(baseline * 100) if baseline is not None else None,
            "edge_pct": _r(edge * 100) if edge is not None else None,
            "ci_pct": [_r(ci[0] * 100), _r(ci[1] * 100)] if ci else None,
            "hit_rate": _r(float((values > 0).mean())) if values.size else None,
            "baseline_hit_rate": _r(base_hit),
        })

    favourable, adverse = [], []
    for i, d in usable:
        if i + EXCURSION_BARS >= hi or i + 1 < ATR_BARS:
            continue
        unit = atr(candles[i + 1 - ATR_BARS: i + 1])
        if unit <= 0:
            continue
        top = float(highs[i + 1: i + 1 + EXCURSION_BARS].max())
        bottom = float(lows[i + 1: i + 1 + EXCURSION_BARS].min())
        up, down = (top - closes[i]) / unit, (closes[i] - bottom) / unit
        favourable.append(up if d == 1 else down)
        adverse.append(down if d == 1 else up)

    headline = next(x for x in horizons if x["h"] == HEADLINE_HORIZON)
    flags = []
    if len(usable) < MIN_SIGNALS:
        flags.append("too_few_signals")
    ci = headline["ci_pct"]
    if ci is None or ci[0] is None or ci[1] is None or ci[0] <= 0 <= ci[1]:
        flags.append("no_edge_detected")

    return {
        "from": int(candles[lo]["time"]) if hi > lo else None,
        "to": int(candles[hi - 1]["time"]) if hi > lo else None,
        "bars": hi - lo,
        "signals": len(usable),
        "skipped_neutral": skipped,
        "long_share": _r(long_share) if usable else None,
        "horizons": horizons,
        "mfe_atr": _r(float(np.mean(favourable))) if favourable else None,
        "mae_atr": _r(float(np.mean(adverse))) if adverse else None,
        "flags": flags,
    }


def study(
    candles: Sequence[Dict[str, Any]],
    signals: Sequence[TapeSignal],
    *,
    start: int,
    split: int,
    end: int,
    neutral: str,
) -> Dict[str, Any]:
    return {
        "seen": period_study(candles, signals, start, split, neutral),
        "unseen": period_study(candles, signals, split, end, neutral),
    }
```

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_backtest_study.py -q`
Expected: 10 passed. `test_forward_return_is_signed_by_direction` compares rounded percentages: `trend()` makes each bar exactly +1%, so `mean_pct` is `1.0` after `_r` rounding to 4 places.

- [ ] **Step 5: Commit**

```bash
git add backend/backtest/study.py backend/tests/test_backtest_study.py
git commit -m "Signal study: forward returns against a direction-matched baseline

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 8: The job runner

**Files:**
- Create: `backend/backtest/runner.py`
- Test: `backend/tests/test_backtest_runner.py`

**Interfaces:**
- Consumes: `BacktestCreate`, `required_bars`, `first_index`, `tape_key`, `replay_range`, `signals_from_tape`, `distinct_setups`, `study`, `TIMEFRAME_MS`, `BacktestRepository`, `HistoryRepository`.
- Produces:
  - `CHUNK_BARS = 500`, `JOB_TIMEOUT_SECONDS = 3600`
  - `class JobCancelled(Exception)`, `class JobFailed(Exception)`
  - `async run_job(job: Dict, *, jobs=None, history=None, clock=time.monotonic, chunk=CHUNK_BARS, to_thread=asyncio.to_thread) -> Optional[Dict]` — returns the report, or `None` when failed or cancelled; always leaves the job in `done`, `failed` or (untouched) `cancelled`.
- Report: `{"meta": {symbol, timeframe, name, params, neutral, split, bars, warmup_bars, from, to, split_time, tape_cached, replay_seconds}, "signals": {"fires", "setups"}, "study": {"seen", "unseen"}}`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_backtest_runner.py`:

```python
"""Orchestration: chunks, progress, the tape cache, cancel, timeout, failure."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backtest import runner
from walks import doji_series

REQUEST = {
    "rule": {"name": "doji", "symbol": "BTCUSDT", "timeframe": "1h", "cooldown_secs": 0,
             "params": {"agent": "sequence", "steps": [{"type": "candle", "shape": "doji"}], "lookback": 60}},
    "neutral": "long",
    "split": 0.7,
}


class FakeJobs:
    def __init__(self, cancel_after=None):
        self.progress, self.tapes, self.finished, self.failed = [], {}, None, None
        self.cancel_after = cancel_after
        self.puts = 0

    async def status_of(self, job_id):
        if self.cancel_after is not None and len(self.progress) >= self.cancel_after:
            return "cancelled"
        return "replaying"

    async def set_progress(self, job_id, status, progress):
        self.progress.append((status, progress))

    async def get_tape(self, key):
        return self.tapes.get(key)

    async def put_tape(self, key, bars, rows):
        self.puts += 1
        self.tapes[key] = rows

    async def finish(self, job_id, report):
        self.finished = report

    async def fail(self, job_id, error):
        self.failed = error


class FakeHistory:
    def __init__(self, candles):
        self.candles = candles

    async def load(self, symbol, timeframe, start_ms=0, end_ms=None):
        return self.candles


async def direct(fn, *args):
    return fn(*args)


def job():
    return {"id": "j1", "request": REQUEST}


async def test_a_job_runs_to_a_report_with_rising_progress():
    jobs = FakeJobs()
    report = await runner.run_job(job(), jobs=jobs, history=FakeHistory(doji_series(900)), chunk=200, to_thread=direct)
    assert jobs.finished == report and jobs.failed is None
    replaying = [p for s, p in jobs.progress if s == "replaying"]
    assert replaying == sorted(replaying) and replaying[-1] == 1.0
    assert jobs.progress[-1][0] == "studying"
    assert report["meta"]["tape_cached"] is False and report["meta"]["warmup_bars"] == 58
    assert report["signals"]["setups"] > 0
    assert set(report["study"]) == {"seen", "unseen"}


async def test_a_second_run_reuses_the_tape_and_reports_the_same_study():
    jobs, history = FakeJobs(), FakeHistory(doji_series(900))
    first = await runner.run_job(job(), jobs=jobs, history=history, chunk=200, to_thread=direct)
    second = await runner.run_job(job(), jobs=jobs, history=history, chunk=200, to_thread=direct)
    assert jobs.puts == 1 and second["meta"]["tape_cached"] is True
    assert second["study"] == first["study"]


async def test_cancel_stops_between_chunks_without_touching_the_job():
    jobs = FakeJobs(cancel_after=1)
    assert await runner.run_job(job(), jobs=jobs, history=FakeHistory(doji_series(900)), chunk=200, to_thread=direct) is None
    assert jobs.finished is None and jobs.failed is None and jobs.puts == 0


async def test_too_little_history_fails_with_a_reason():
    jobs = FakeJobs()
    await runner.run_job(job(), jobs=jobs, history=FakeHistory(doji_series(100)), to_thread=direct)
    assert "100 bars" in jobs.failed and "needs 359" in jobs.failed


async def test_a_job_past_its_time_limit_fails():
    ticks = iter([0.0] + [runner.JOB_TIMEOUT_SECONDS + 1.0] * 50)
    jobs = FakeJobs()
    await runner.run_job(job(), jobs=jobs, history=FakeHistory(doji_series(900)), chunk=200,
                         to_thread=direct, clock=lambda: next(ticks))
    assert jobs.failed.startswith("timeout")
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_backtest_runner.py -q`
Expected: `ImportError: cannot import name 'runner'`.

- [ ] **Step 3: Implement**

`backend/backtest/runner.py`:

```python
"""
Run one backtest job end to end.

Load history, replay it into a candidate tape in chunks (or take the cached
tape), turn the tape into fires, study them on seen and unseen bars, write the
report. Between chunks the runner reports progress and checks whether the job
was cancelled or has run too long; the replay itself runs in a thread so the
worker's heartbeat keeps beating.
"""
import asyncio
import time
from typing import Any, Dict, Optional

from backtest.replay import first_index, replay_range, tape_key
from backtest.signals import distinct_setups, signals_from_tape
from backtest.study import study
from models.backtest_schemas import BacktestCreate, required_bars
from services.history_service import TIMEFRAME_MS

CHUNK_BARS = 500
JOB_TIMEOUT_SECONDS = 3600


class JobCancelled(Exception):
    """The owner cancelled the job; leave it as they left it."""


class JobFailed(Exception):
    """A reason safe to show the owner."""


def _repos(jobs, history):
    if jobs is None:
        from repositories.backtest_repository import BacktestRepository

        jobs = BacktestRepository
    if history is None:
        from repositories.history_repository import HistoryRepository

        history = HistoryRepository
    return jobs, history


async def run_job(
    job: Dict[str, Any],
    *,
    jobs: Any = None,
    history: Any = None,
    clock=time.monotonic,
    chunk: int = CHUNK_BARS,
    to_thread=asyncio.to_thread,
) -> Optional[Dict[str, Any]]:
    jobs, history = _repos(jobs, history)
    started = clock()
    try:
        report = await _run(job, jobs, history, clock, started, chunk, to_thread)
    except JobCancelled:
        return None
    except Exception as exc:  # noqa: BLE001 - every failure must land on the job
        await jobs.fail(job["id"], str(exc)[:500] or exc.__class__.__name__)
        return None
    await jobs.finish(job["id"], report)
    return report


async def _checkpoint(job, jobs, status, progress, clock, started) -> None:
    if await jobs.status_of(job["id"]) == "cancelled":
        raise JobCancelled()
    if clock() - started > JOB_TIMEOUT_SECONDS:
        raise JobFailed("timeout: the backtest ran for more than an hour")
    await jobs.set_progress(job["id"], status, round(progress, 4))


async def _run(job, jobs, history, clock, started, chunk, to_thread) -> Dict[str, Any]:
    request = BacktestCreate(**job["request"])
    rule = request.rule
    params = rule.params.model_dump()
    symbol, timeframe = rule.symbol.upper(), rule.timeframe

    candles = await history.load(symbol, timeframe)
    needed = required_bars(int(params["lookback"]))
    if len(candles) < needed:
        raise JobFailed(
            f"{symbol} {timeframe} has {len(candles)} bars of history; this rule needs {needed}"
        )

    start, end = first_index(params), len(candles)
    split = start + int((end - start) * request.split)
    key = tape_key(symbol, timeframe, params, candles[-1]["time"])

    tape = await jobs.get_tape(key)
    cached = tape is not None
    replay_started = clock()
    if tape is None:
        tape = []
        for lo in range(start, end, chunk):
            hi = min(end, lo + chunk)
            await _checkpoint(job, jobs, "replaying", (lo - start) / (end - start), clock, started)
            tape.extend(await to_thread(replay_range, candles, params, lo, hi))
        await _checkpoint(job, jobs, "replaying", 1.0, clock, started)
        await jobs.put_tape(key, end - start, tape)
    replay_seconds = clock() - replay_started

    await _checkpoint(job, jobs, "studying", 1.0, clock, started)
    fires = signals_from_tape(
        tape, candles, params,
        timeframe_ms=TIMEFRAME_MS[timeframe],
        persist_bars=rule.resolved_persist_bars(),
        cooldown_secs=rule.cooldown_secs,
        start=start, end=end,
    )
    setups = distinct_setups(fires)

    return {
        "meta": {
            "symbol": symbol,
            "timeframe": timeframe,
            "name": rule.name,
            "params": params,
            "neutral": request.neutral,
            "split": request.split,
            "bars": end - start,
            "warmup_bars": start,
            "from": int(candles[start]["time"]),
            "to": int(candles[-1]["time"]),
            "split_time": int(candles[split]["time"]),
            "tape_cached": cached,
            "replay_seconds": round(replay_seconds, 1),
        },
        "signals": {"fires": len(fires), "setups": len(setups)},
        "study": study(candles, setups, start=start, split=split, end=end, neutral=request.neutral),
    }
```

Note on the cancel test: with `cancel_after=1`, the first checkpoint records progress, the second sees `cancelled` and raises before any tape is stored.

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_backtest_runner.py -q`
Expected: 5 passed. (`needs 359` = `window_size(60)` 59 + 300.)

- [ ] **Step 5: Commit**

```bash
git add backend/backtest/runner.py backend/tests/test_backtest_runner.py
git commit -m "Run a backtest job: chunked replay, cached tape, cancel and timeout

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 9: The worker's job loop

**Files:**
- Modify: `backend/worker.py`
- Test: `backend/tests/test_worker.py` (append; one existing test updated for the new `build_scheduler` argument)

**Interfaces:**
- Consumes: `BacktestRepository.requeue_running/claim_next/evict_tapes`, `run_job`.
- Produces: `POLL_SECONDS = 5`, `EVICT_JOB_ID = "tape_eviction"`, `async job_loop(stop: asyncio.Event, *, jobs=None, run=None, poll=POLL_SECONDS) -> None`, `build_scheduler(topup, heartbeat, evict=None)` (adds a 6-hourly `evict` job when given).

- [ ] **Step 1: Write the failing tests** (append to `backend/tests/test_worker.py`)

```python
import asyncio


async def test_job_loop_requeues_then_runs_claimed_jobs_in_order():
    ran, stop = [], asyncio.Event()

    class Jobs:
        queue = [{"id": "a"}, {"id": "b"}]
        requeued = False

        async def requeue_running(self):
            Jobs.requeued = True
            return 1

        async def claim_next(self):
            if not Jobs.queue:
                stop.set()
                return None
            return Jobs.queue.pop(0)

    async def run(job):
        ran.append(job["id"])

    await asyncio.wait_for(worker.job_loop(stop, jobs=Jobs(), run=run, poll=0.01), timeout=2)
    assert Jobs.requeued and ran == ["a", "b"]


async def test_scheduler_evicts_tapes_when_asked():
    async def noop():
        pass

    scheduler = worker.build_scheduler(noop, lambda: None, evict=noop)
    assert scheduler.get_job(worker.EVICT_JOB_ID).trigger.interval.total_seconds() == 6 * 3600
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_worker.py -q`
Expected: the two new tests fail with `AttributeError: module 'worker' has no attribute 'job_loop'`.

- [ ] **Step 3: Implement** in `backend/worker.py`

Update the module docstring's second paragraph to: `Runs beside the API in its own container, at a lower CPU share, so nothing it does can delay a live alert. It keeps candles_history current and runs backtest jobs one at a time.`

Add imports:

```python
from backtest.runner import run_job
from repositories.backtest_repository import BacktestRepository
```

Add constants under `TOPUP_JOB_ID`:

```python
EVICT_JOB_ID = "tape_eviction"
POLL_SECONDS = 5
```

Change `build_scheduler` to accept and schedule eviction:

```python
def build_scheduler(topup, heartbeat, evict=None) -> AsyncIOScheduler:
```

and before `return scheduler` add:

```python
    if evict is not None:
        scheduler.add_job(
            evict,
            trigger=IntervalTrigger(hours=6),
            id=EVICT_JOB_ID,
            max_instances=1,
            coalesce=True,
            replace_existing=True,
        )
```

Add the loop after `_topup`:

```python
async def job_loop(stop: asyncio.Event, *, jobs=None, run=None, poll: float = POLL_SECONDS) -> None:
    """
    One job at a time, oldest first. A job still marked running when the worker
    starts was interrupted - there is only one worker - so it goes back on the
    queue and resumes from whatever tape it had finished.
    """
    jobs = jobs or BacktestRepository
    run = run or run_job
    requeued = await jobs.requeue_running()
    if requeued:
        print(f"[backtest] requeued {requeued} interrupted job(s)", flush=True)

    while not stop.is_set():
        job = await jobs.claim_next()
        if job is None:
            try:
                await asyncio.wait_for(stop.wait(), timeout=poll)
            except asyncio.TimeoutError:
                pass
            continue
        print(f"[backtest] {job['id']} started", flush=True)
        await run(job)
        print(f"[backtest] {job['id']} ended", flush=True)
```

In `main()`, change `scheduler = build_scheduler(_topup, beat)` to `scheduler = build_scheduler(_topup, beat, evict=BacktestRepository.evict_tapes)`, and replace `await stop.wait()` with:

```python
    loop_task = asyncio.create_task(job_loop(stop))
    await stop.wait()
    loop_task.cancel()
```

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_worker.py -q`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/worker.py backend/tests/test_worker.py
git commit -m "Worker claims and runs backtest jobs, and evicts old tapes

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 10: The backtest API

**Files:**
- Create: `backend/controllers/backtest_controller.py`
- Modify: `backend/controllers/__init__.py`, `backend/main.py` (import + `app.include_router(backtest_router)` after `history_router`), `backend/tests/test_app_imports.py` (add `"controllers.backtest_controller",` first in `CONTROLLERS`)
- Test: `backend/tests/test_backtest_controller.py`

**Interfaces:**
- Consumes: `require_owner` (from `controllers.rules_controller`), `BacktestCreate`, `required_bars`, `BacktestRepository`, `history_controller.get_coverage`.
- Produces: `router` with `POST /api/backtests` (201 `{id, status}`), `GET /api/backtests`, `GET /api/backtests/{job_id}`, `DELETE /api/backtests/{job_id}` (`{result}`); `serialize(job: Dict) -> Dict`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_backtest_controller.py`:

```python
"""The backtest API: ownership, one job at a time, history required."""
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from controllers import backtest_controller as bc
from controllers.rules_controller import require_owner

BODY = {"rule": {"name": "doji", "symbol": "BTCUSDT", "timeframe": "1h",
                 "params": {"agent": "sequence", "steps": [{"type": "candle", "shape": "doji"}]}}}
JOB_ID = str(uuid.uuid4())


class Jobs:
    def __init__(self, active=0):
        self.active, self.created = active, None

    async def count_active(self, owner):
        return self.active

    async def create(self, owner, request):
        self.created = (owner, request)
        return {"id": uuid.UUID(JOB_ID), "status": "queued", "created_at": datetime.now(timezone.utc)}

    async def get_for_owner(self, job_id, owner):
        if owner != "0xabc":
            return None
        return {"id": uuid.UUID(job_id), "owner_key": owner, "status": "done", "progress": 1.0,
                "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc), "started_at": None,
                "finished_at": None, "request": BODY, "report": {"study": {}}, "error": None}

    async def cancel_or_delete(self, job_id, owner):
        return "cancelled" if owner == "0xabc" else None


def client(monkeypatch, jobs, bars=100_000, owner="0xabc"):
    async def coverage():
        return {"depth_days": {}, "series": [{"symbol": "BTCUSDT", "timeframe": "1h", "bars": bars}]}

    monkeypatch.setattr(bc, "BacktestRepository", jobs)
    monkeypatch.setattr(bc, "get_coverage", coverage)
    app = FastAPI()
    app.include_router(bc.router)
    if owner:
        app.dependency_overrides[require_owner] = lambda: owner
    return TestClient(app)


def test_signed_out_is_401(monkeypatch):
    assert client(monkeypatch, Jobs(), owner=None).post("/api/backtests", json=BODY).status_code == 401


def test_create_queues_a_job_for_the_owner(monkeypatch):
    jobs = Jobs()
    res = client(monkeypatch, jobs).post("/api/backtests", json=BODY)
    assert res.status_code == 201 and res.json() == {"id": JOB_ID, "status": "queued"}
    owner, request = jobs.created
    assert owner == "0xabc" and request["rule"]["params"]["lookback"] == 300 and request["split"] == 0.7


def test_a_second_active_job_is_429(monkeypatch):
    assert client(monkeypatch, Jobs(active=1)).post("/api/backtests", json=BODY).status_code == 429


def test_missing_history_is_409_with_the_numbers(monkeypatch):
    res = client(monkeypatch, Jobs(), bars=400).post("/api/backtests", json=BODY)
    assert res.status_code == 409 and "400" in res.json()["detail"] and "599" in res.json()["detail"]


def test_unsupported_timeframe_is_422(monkeypatch):
    body = {"rule": {**BODY["rule"], "timeframe": "1m"}}
    assert client(monkeypatch, Jobs()).post("/api/backtests", json=body).status_code == 422


def test_get_is_scoped_to_the_owner(monkeypatch):
    assert client(monkeypatch, Jobs()).get(f"/api/backtests/{JOB_ID}").json()["status"] == "done"
    assert client(monkeypatch, Jobs(), owner="0xother").get(f"/api/backtests/{JOB_ID}").status_code == 404


def test_delete_reports_what_happened(monkeypatch):
    assert client(monkeypatch, Jobs()).delete(f"/api/backtests/{JOB_ID}").json() == {"result": "cancelled"}
    assert client(monkeypatch, Jobs(), owner="0xother").delete(f"/api/backtests/{JOB_ID}").status_code == 404
```

Also add `"controllers.backtest_controller",` as the first entry of `CONTROLLERS` in `backend/tests/test_app_imports.py`.

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_backtest_controller.py tests/test_app_imports.py -q`
Expected: `ImportError: cannot import name 'backtest_controller'`.

- [ ] **Step 3: Implement**

`backend/controllers/backtest_controller.py`:

```python
"""
Backtests, owned by the signed-in wallet.

A backtest costs real CPU on a small machine, so it needs a session, and each
wallet may have one queued or running at a time. Ownership works as it does
for rules: another wallet's job id is a 404, never a 403.
"""
from typing import Any, Dict, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from controllers.history_controller import get_coverage
from controllers.rules_controller import require_owner
from models.backtest_schemas import BacktestCreate, required_bars
from repositories.backtest_repository import BacktestRepository

router = APIRouter(prefix="/api/backtests", tags=["Backtests"])


def _iso(value):
    return value.isoformat() if value is not None else None


def serialize(job: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": str(job["id"]),
        "status": job["status"],
        "progress": float(job.get("progress") or 0),
        "created_at": _iso(job.get("created_at")),
        "started_at": _iso(job.get("started_at")),
        "finished_at": _iso(job.get("finished_at")),
        "request": job.get("request"),
        "report": job.get("report"),
        "error": job.get("error"),
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_backtest(body: BacktestCreate, owner: str = Depends(require_owner)) -> Dict[str, Any]:
    if await BacktestRepository.count_active(owner):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="You already have a backtest running. Wait for it to finish or cancel it.",
        )

    rule = body.rule
    symbol = rule.symbol.upper()
    needed = required_bars(rule.params.lookback)
    coverage = await get_coverage()
    have = next(
        (s["bars"] for s in coverage["series"] if s["symbol"] == symbol and s["timeframe"] == rule.timeframe),
        0,
    )
    if have < needed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{symbol} {rule.timeframe} has {have} bars of history; this rule needs {needed}.",
        )

    job = await BacktestRepository.create(owner, body.model_dump(mode="json"))
    return {"id": str(job["id"]), "status": job["status"]}


@router.get("")
async def list_backtests(owner: str = Depends(require_owner)) -> List[Dict[str, Any]]:
    return [serialize({**job, "report": None}) for job in await BacktestRepository.list_for_owner(owner)]


@router.get("/{job_id}")
async def get_backtest(job_id: UUID, owner: str = Depends(require_owner)) -> Dict[str, Any]:
    job = await BacktestRepository.get_for_owner(str(job_id), owner)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Backtest not found")
    return serialize(job)


@router.delete("/{job_id}")
async def cancel_backtest(job_id: UUID, owner: str = Depends(require_owner)) -> Dict[str, str]:
    result = await BacktestRepository.cancel_or_delete(str(job_id), owner)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Backtest not found")
    return {"result": result}
```

`backend/controllers/__init__.py`: add `from .backtest_controller import router as backtest_router` and `"backtest_router",` to `__all__`.

`backend/main.py`: add `backtest_router,` to the `from controllers import (...)` block and `app.include_router(backtest_router)` after `app.include_router(history_router)`.

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_backtest_controller.py tests/test_app_imports.py -q`
Expected: 7 + 10 passed.

- [ ] **Step 5: Full backend suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: **395 passed**, 0 failed (334 + 12 rule_decision + 1 migration + 3 repository + 6 schemas + 9 replay + 5 signals + 10 study + 5 runner + 2 worker + 7 controller + 1 app-import).

- [ ] **Step 6: Commit**

```bash
git add backend/controllers/backtest_controller.py backend/controllers/__init__.py backend/main.py backend/tests/test_backtest_controller.py backend/tests/test_app_imports.py
git commit -m "Backtest API: one job per wallet, history required

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 11: Backtest button and report sheet

**Files:**
- Modify: `frontend/lib/rules.ts` (append one export line)
- Create: `frontend/lib/backtests.ts`, `frontend/components/backtest-sheet.tsx`, `frontend/tests/backtests.test.ts`
- Modify: `frontend/components/analysis-panel.tsx`, `frontend/components/chat-panel.tsx`

**Interfaces:**
- Consumes: `API_BASE`, `authHeaders`, `failResponse`, `UnauthorizedError`, `RuleParams`; backend routes from Task 10.
- Produces (`lib/backtests.ts`): types `BacktestStatus`, `Neutral`, `HorizonStudy`, `PeriodStudy`, `BacktestReport`, `Backtest`, `BacktestRule`; `ACTIVE_STATUSES`, `BACKTEST_TIMEFRAMES`; `createBacktest(rule, {neutral, split})`, `getBacktest(id)`, `cancelBacktest(id)`; pure `canBeNeutral(params)`, `headline(period)`, `verdict(report)`, `fmtPct(value)`.
- Produces: default export `BacktestSheet({ rule, open, onOpenChange })`.

- [ ] **Step 1: Write the failing tests**

`frontend/tests/backtests.test.ts`:

```ts
import { describe, expect, it } from "vitest"

import { canBeNeutral, fmtPct, verdict, type BacktestReport, type PeriodStudy } from "@/lib/backtests"

function period(over: Partial<PeriodStudy> = {}, edge = 0.4, ci: [number, number] | null = [0.1, 0.7]): PeriodStudy {
  return {
    from: 0, to: 1, bars: 1000, signals: 45, skipped_neutral: 0, long_share: 0.5,
    horizons: [1, 5, 10, 20].map((h) => ({
      h, signals: 45, mean_pct: edge, baseline_pct: 0, edge_pct: edge, ci_pct: ci, hit_rate: 0.55, baseline_hit_rate: 0.5,
    })),
    mfe_atr: 1.2, mae_atr: 0.8, flags: [],
    ...over,
  }
}

function report(unseen: PeriodStudy): BacktestReport {
  return {
    meta: { symbol: "BTCUSDT", timeframe: "1h", name: "x", neutral: "skip", split: 0.7, bars: 1, warmup_bars: 0,
            from: 0, to: 1, split_time: 0, tape_cached: false, replay_seconds: 1 },
    signals: { fires: 50, setups: 45 },
    study: { seen: period(), unseen },
  }
}

describe("canBeNeutral", () => {
  it("is true only for sequences ending on a directionless candle", () => {
    expect(canBeNeutral({ agent: "sequence", steps: [{ type: "candle", shape: "doji" }], within_bars: 3 })).toBe(true)
    expect(canBeNeutral({ agent: "sequence", steps: [{ type: "candle", shape: "hammer" }], within_bars: 3 })).toBe(false)
    expect(canBeNeutral({ agent: "pattern", kinds: ["W"] })).toBe(false)
  })
})

describe("verdict", () => {
  it("says too few before anything else", () => {
    expect(verdict(report(period({ signals: 12, flags: ["too_few_signals", "no_edge_detected"] })))).toMatch(/Only 12 unseen signals/)
  })
  it("says no edge plainly", () => {
    expect(verdict(report(period({ flags: ["no_edge_detected"] }, 0.05, [-0.3, 0.4])))).toMatch(/^No edge on unseen data/)
  })
  it("reports an edge with its interval", () => {
    expect(verdict(report(period()))).toBe(
      "Unseen edge +0.40% per signal over 10 bars (95% CI +0.10% to +0.70%), across 45 signals.",
    )
  })
  it("handles no unseen signals", () => {
    expect(verdict(report(period({ signals: 0, flags: ["too_few_signals", "no_edge_detected"] }, 0, null)))).toBe(
      "No signals on unseen data — nothing to judge.",
    )
  })
})

describe("fmtPct", () => {
  it("signs and dashes", () => {
    expect(fmtPct(0.4)).toBe("+0.40%")
    expect(fmtPct(-1.234)).toBe("-1.23%")
    expect(fmtPct(null)).toBe("—")
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run (from `frontend/`): `npx vitest run tests/backtests.test.ts`
Expected: FAIL — cannot resolve `@/lib/backtests`.

- [ ] **Step 3: Export the auth helpers from `frontend/lib/rules.ts`**

Append at the end of the file:

```ts
/** Shared with the backtest client, which authenticates the same way. */
export { headers as authHeaders, fail as failResponse }
```

- [ ] **Step 4: Create `frontend/lib/backtests.ts`**

```ts
import { API_BASE } from "@/lib/api"
import { authHeaders, failResponse, type RuleParams } from "@/lib/rules"

export type BacktestStatus = "queued" | "replaying" | "studying" | "tuning" | "done" | "failed" | "cancelled"
export type Neutral = "skip" | "long" | "short"

export const ACTIVE_STATUSES: BacktestStatus[] = ["queued", "replaying", "studying", "tuning"]
export const BACKTEST_TIMEFRAMES = ["5m", "15m", "1h", "1d"] as const
export const HEADLINE_HORIZON = 10

export interface HorizonStudy {
  h: number
  signals: number
  mean_pct: number | null
  baseline_pct: number | null
  edge_pct: number | null
  ci_pct: [number, number] | null
  hit_rate: number | null
  baseline_hit_rate: number | null
}

export interface PeriodStudy {
  from: number | null
  to: number | null
  bars: number
  signals: number
  skipped_neutral: number
  long_share: number | null
  horizons: HorizonStudy[]
  mfe_atr: number | null
  mae_atr: number | null
  flags: string[]
}

export interface BacktestReport {
  meta: {
    symbol: string
    timeframe: string
    name: string
    neutral: Neutral
    split: number
    bars: number
    warmup_bars: number
    from: number
    to: number
    split_time: number
    tape_cached: boolean
    replay_seconds: number
  }
  signals: { fires: number; setups: number }
  study: { seen: PeriodStudy; unseen: PeriodStudy }
}

export interface Backtest {
  id: string
  status: BacktestStatus
  progress: number
  created_at: string | null
  started_at: string | null
  finished_at: string | null
  error: string | null
  report: BacktestReport | null
}

/** A rule as the Strategy panel lists it, or as the chat drafts it. */
export interface BacktestRule {
  name: string
  symbol: string
  timeframe: string
  params: RuleParams | Record<string, unknown>
  cooldown_secs?: number
  persist_bars?: number
}

export async function createBacktest(
  rule: BacktestRule,
  options: { neutral: Neutral; split: number },
): Promise<{ id: string; status: BacktestStatus }> {
  const res = await fetch(`${API_BASE}/api/backtests`, {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify({
      rule: {
        name: rule.name,
        symbol: rule.symbol,
        timeframe: rule.timeframe,
        params: rule.params,
        cooldown_secs: rule.cooldown_secs,
        persist_bars: rule.persist_bars,
      },
      neutral: options.neutral,
      split: options.split,
    }),
  })
  if (!res.ok) await failResponse(res, "Could not start the backtest")
  return res.json()
}

export async function getBacktest(id: string): Promise<Backtest> {
  const res = await fetch(`${API_BASE}/api/backtests/${id}`, { headers: authHeaders() })
  if (!res.ok) await failResponse(res, "Could not load the backtest")
  return res.json()
}

export async function cancelBacktest(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/backtests/${id}`, { method: "DELETE", headers: authHeaders() })
  if (!res.ok) await failResponse(res, "Could not cancel the backtest")
}

const DIRECTIONLESS = new Set(["doji", "inside_bar"])

/** Whether signals from this rule can have no direction, so the user must say how to read them. */
export function canBeNeutral(params: BacktestRule["params"]): boolean {
  const p = params as { agent?: string; steps?: { type?: string; shape?: string }[] }
  if (p.agent !== "sequence" || !p.steps?.length) return false
  const last = p.steps[p.steps.length - 1]
  return last.type === "candle" && DIRECTIONLESS.has(last.shape ?? "")
}

export function headline(period: PeriodStudy): HorizonStudy | undefined {
  return period.horizons.find((h) => h.h === HEADLINE_HORIZON)
}

export function fmtPct(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—"
  return `${value > 0 ? "+" : ""}${value.toFixed(2)}%`
}

/** One sentence on the unseen result, the only number that was not fitted to anything. */
export function verdict(report: BacktestReport): string {
  const unseen = report.study.unseen
  const h = headline(unseen)
  if (unseen.signals === 0 || !h) return "No signals on unseen data — nothing to judge."
  if (unseen.flags.includes("too_few_signals")) {
    return `Only ${unseen.signals} unseen signals — too few to judge.`
  }
  const ci = h.ci_pct ? ` (95% CI ${fmtPct(h.ci_pct[0])} to ${fmtPct(h.ci_pct[1])})` : ""
  if (unseen.flags.includes("no_edge_detected")) {
    return `No edge on unseen data: ${fmtPct(h.edge_pct)} per signal vs the market over ${HEADLINE_HORIZON} bars${ci}.`
  }
  return `Unseen edge ${fmtPct(h.edge_pct)} per signal over ${HEADLINE_HORIZON} bars${ci}, across ${unseen.signals} signals.`
}
```

- [ ] **Step 5: Run the unit tests**

Run: `npx vitest run tests/backtests.test.ts`
Expected: 6 passed.

- [ ] **Step 6: Create `frontend/components/backtest-sheet.tsx`**

```tsx
"use client"

import { useEffect, useState } from "react"
import { FlaskConical, Loader2 } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Progress } from "@/components/ui/progress"
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import {
  ACTIVE_STATUSES,
  BACKTEST_TIMEFRAMES,
  canBeNeutral,
  cancelBacktest,
  createBacktest,
  fmtPct,
  getBacktest,
  verdict,
  type Backtest,
  type BacktestRule,
  type Neutral,
  type PeriodStudy,
} from "@/lib/backtests"
import { UnauthorizedError } from "@/lib/rules"
import { cn } from "@/lib/utils"

const POLL_MS = 3000
const SPLITS = [0.6, 0.7, 0.8]
const STAGE: Record<string, string> = {
  queued: "Waiting for the worker",
  replaying: "Replaying history bar by bar",
  studying: "Measuring what followed each signal",
  tuning: "Tuning on seen data",
}

function day(ms: number | null) {
  return ms === null ? "—" : new Date(ms).toISOString().slice(0, 10)
}

function StudyTable({ title, period }: { title: string; period: PeriodStudy }) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between">
        <h3 className="text-xs font-semibold text-foreground">{title}</h3>
        <span className="font-mono text-[10px] text-muted-foreground">
          {day(period.from)} → {day(period.to)} · {period.signals} signals
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-[11px]">
          <thead className="text-muted-foreground">
            <tr className="text-left">
              <th className="py-1 pr-2 font-normal">After</th>
              <th className="py-1 pr-2 font-normal">Signal</th>
              <th className="py-1 pr-2 font-normal">Market</th>
              <th className="py-1 pr-2 font-normal">Edge</th>
              <th className="py-1 pr-2 font-normal">95% CI</th>
              <th className="py-1 font-normal">Hit</th>
            </tr>
          </thead>
          <tbody className="font-mono">
            {period.horizons.map((h) => (
              <tr key={h.h} className="border-t border-border">
                <td className="py-1 pr-2">{h.h} bars</td>
                <td className="py-1 pr-2">{fmtPct(h.mean_pct)}</td>
                <td className="py-1 pr-2 text-muted-foreground">{fmtPct(h.baseline_pct)}</td>
                <td className={cn("py-1 pr-2", (h.edge_pct ?? 0) > 0 ? "text-emerald-500" : "text-red-400")}>
                  {fmtPct(h.edge_pct)}
                </td>
                <td className="py-1 pr-2 text-muted-foreground">
                  {h.ci_pct ? `${fmtPct(h.ci_pct[0])} … ${fmtPct(h.ci_pct[1])}` : "—"}
                </td>
                <td className="py-1">{h.hit_rate === null ? "—" : `${Math.round(h.hit_rate * 100)}%`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-[10px] text-muted-foreground">
        Moved for it {period.mfe_atr?.toFixed(2) ?? "—"} ATR, against it {period.mae_atr?.toFixed(2) ?? "—"} ATR
        within 20 bars
        {period.skipped_neutral > 0 && ` · ${period.skipped_neutral} directionless signals skipped`}
        {period.flags.includes("too_few_signals") && " · too few signals to judge"}
      </p>
    </div>
  )
}

export default function BacktestSheet({
  rule,
  open,
  onOpenChange,
}: {
  rule: BacktestRule | null
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const [neutral, setNeutral] = useState<Neutral>("skip")
  const [split, setSplit] = useState(0.7)
  const [job, setJob] = useState<Backtest | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [starting, setStarting] = useState(false)

  // Closing the sheet forgets the view, not the job: it keeps running on the
  // server. Slice 4 adds a list to reopen it from.
  useEffect(() => {
    if (!open) {
      setJob(null)
      setError(null)
      setStarting(false)
    }
  }, [open])

  const jobId = job?.id
  const running = job !== null && ACTIVE_STATUSES.includes(job.status)
  useEffect(() => {
    if (!jobId || !running) return
    const timer = setInterval(async () => {
      try {
        setJob(await getBacktest(jobId))
      } catch (err) {
        setError(err instanceof Error ? err.message : "Lost track of the backtest")
      }
    }, POLL_MS)
    return () => clearInterval(timer)
  }, [jobId, running])

  if (!rule) return null
  const supported = (BACKTEST_TIMEFRAMES as readonly string[]).includes(rule.timeframe)
  const neutralChoice = canBeNeutral(rule.params)

  async function start() {
    if (!rule) return
    setStarting(true)
    setError(null)
    try {
      const { id } = await createBacktest(rule, { neutral, split })
      setJob(await getBacktest(id))
    } catch (err) {
      setError(
        err instanceof UnauthorizedError
          ? "Sign in with your wallet in the Strategy panel first."
          : err instanceof Error
            ? err.message
            : "Could not start the backtest",
      )
    } finally {
      setStarting(false)
    }
  }

  async function cancel() {
    if (!job) return
    try {
      await cancelBacktest(job.id)
      setJob({ ...job, status: "cancelled" })
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not cancel")
    }
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-lg">
        <SheetHeader>
          <SheetTitle className="flex items-center gap-2">
            <FlaskConical className="h-4 w-4 text-primary" /> Backtest
          </SheetTitle>
          <SheetDescription>
            {rule.name} · {rule.symbol} {rule.timeframe}
          </SheetDescription>
        </SheetHeader>

        <div className="space-y-4 px-4 pb-6">
          {!supported && (
            <p className="text-xs text-muted-foreground">Backtests run on 5m, 15m, 1h and 1d charts.</p>
          )}

          {supported && job === null && (
            <div className="space-y-3">
              <p className="text-xs leading-relaxed text-muted-foreground">
                Replays this rule over stored history exactly as the live alert would have run, then measures
                what price did after each signal against the market as a whole. The last part of history is
                held back as unseen data.
              </p>
              {neutralChoice && (
                <div className="space-y-1">
                  <span className="text-[11px] text-muted-foreground">This candle has no direction. Read it as</span>
                  <div className="flex gap-1.5">
                    {(["skip", "long", "short"] as Neutral[]).map((n) => (
                      <Button key={n} size="sm" variant={neutral === n ? "default" : "outline"}
                        className="h-7 flex-1 text-xs" onClick={() => setNeutral(n)}>
                        {n === "skip" ? "Skip it" : n === "long" ? "Long" : "Short"}
                      </Button>
                    ))}
                  </div>
                </div>
              )}
              <div className="space-y-1">
                <span className="text-[11px] text-muted-foreground">Seen / unseen split</span>
                <div className="flex gap-1.5">
                  {SPLITS.map((s) => (
                    <Button key={s} size="sm" variant={split === s ? "default" : "outline"}
                      className="h-7 flex-1 font-mono text-xs" onClick={() => setSplit(s)}>
                      {Math.round(s * 100)} / {Math.round((1 - s) * 100)}
                    </Button>
                  ))}
                </div>
              </div>
              <Button onClick={start} disabled={starting} className="h-9 w-full text-xs">
                {starting ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> : <FlaskConical className="mr-1 h-3.5 w-3.5" />}
                Run backtest
              </Button>
            </div>
          )}

          {job && ACTIVE_STATUSES.includes(job.status) && (
            <div className="space-y-2">
              <p className="text-xs text-foreground">{STAGE[job.status]}…</p>
              <Progress value={Math.round(job.progress * 100)} />
              <div className="flex items-center justify-between">
                <span className="font-mono text-[10px] text-muted-foreground">{Math.round(job.progress * 100)}%</span>
                <Button size="sm" variant="outline" className="h-7 text-xs" onClick={cancel}>Cancel</Button>
              </div>
              <p className="text-[10px] text-muted-foreground">
                The first run of a rule replays every bar and can take many minutes. It keeps running if you close this.
              </p>
            </div>
          )}

          {job?.status === "failed" && <p className="text-xs text-destructive">{job.error}</p>}
          {job?.status === "cancelled" && <p className="text-xs text-muted-foreground">Cancelled.</p>}

          {job?.status === "done" && job.report && (
            <div className="space-y-4">
              <p className="rounded-md border border-border bg-secondary px-3 py-2 text-xs text-foreground">
                {verdict(job.report)}
              </p>
              <StudyTable title="Unseen" period={job.report.study.unseen} />
              <StudyTable title="Seen" period={job.report.study.seen} />
              <p className="text-[10px] leading-relaxed text-muted-foreground">
                {job.report.signals.fires} alerts from {job.report.signals.setups} distinct setups over{" "}
                {job.report.meta.bars.toLocaleString()} bars. Each setup counts once.{" "}
                {job.report.meta.tape_cached ? "Replay reused from cache." : `Replay took ${Math.round(job.report.meta.replay_seconds)}s.`}{" "}
                Past behaviour on this data is not a forecast.
              </p>
            </div>
          )}

          {error && <p className="text-xs text-destructive">{error}</p>}
        </div>
      </SheetContent>
    </Sheet>
  )
}
```

- [ ] **Step 7: Add the button to Strategy panel rules** (`frontend/components/analysis-panel.tsx`)

1. Import line 14 becomes: `import { AlertCircle, Bell, FlaskConical, Loader2, Plus, Trash2, Wallet, Zap } from "lucide-react"`.
2. After the `import { cn } from "@/lib/utils"` line add:
   ```tsx
   import BacktestSheet from "@/components/backtest-sheet"
   import type { BacktestRule } from "@/lib/backtests"
   ```
3. Next to the component's other `useState` hooks (beside `testing`/`testResult`) add:
   ```tsx
   const [backtestRule, setBacktestRule] = useState<BacktestRule | null>(null)
   ```
4. In the Armed list, immediately before the `<Button onClick={() => handleTest(rule)}` element, add:
   ```tsx
                    <Button
                      onClick={() => setBacktestRule(rule)}
                      variant="ghost"
                      size="sm"
                      className="h-6 gap-1 px-2 text-[11px]"
                      title="Backtest this rule on stored history"
                    >
                      <FlaskConical className="h-3 w-3" />
                      Backtest
                    </Button>
   ```
5. At the end of the file, replace
   ```tsx
         </Tabs>
       </div>
     )
   }
   ```
   with
   ```tsx
         </Tabs>
         <BacktestSheet
           rule={backtestRule}
           open={backtestRule !== null}
           onOpenChange={(next) => {
             if (!next) setBacktestRule(null)
           }}
         />
       </div>
     )
   }
   ```

- [ ] **Step 8: Add the button to chat draft cards** (`frontend/components/chat-panel.tsx`)

1. Import line 7: add `FlaskConical` to the `lucide-react` import list.
2. After the `@/lib/rules` import block add:
   ```tsx
   import BacktestSheet from "@/components/backtest-sheet"
   import type { BacktestRule } from "@/lib/backtests"
   ```
3. Beside the `marked` state add: `const [backtestRule, setBacktestRule] = useState<BacktestRule | null>(null)`.
4. In the draft card's button row, between the **Arm rule** button and the **Dismiss** button, add:
   ```tsx
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => setBacktestRule(message.ruleDraft!.draft)}
                            className="h-8 flex-1 text-xs"
                          >
                            <FlaskConical className="mr-1 h-3.5 w-3.5" />
                            Backtest
                          </Button>
   ```
5. The component's final lines are `        </p>\n      </div>\n    </div>\n  )\n}`. Replace the last `    </div>\n  )\n}` with:
   ```tsx
      <BacktestSheet
        rule={backtestRule}
        open={backtestRule !== null}
        onOpenChange={(next) => {
          if (!next) setBacktestRule(null)
        }}
      />
    </div>
  )
}
   ```

- [ ] **Step 9: Type-check and test**

Run (from `frontend/`): `npx tsc --noEmit -p .` — expected: only the pre-existing `tests/sw.test.ts` error.
Run: `npx vitest run` — expected: **56 passed**.

- [ ] **Step 10: Commit**

```bash
git add frontend/lib/rules.ts frontend/lib/backtests.ts frontend/components/backtest-sheet.tsx frontend/tests/backtests.test.ts frontend/components/analysis-panel.tsx frontend/components/chat-panel.tsx
git commit -m "Backtest any rule or chat draft from a report sheet

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 12: Record the decisions, ship, verify on production

**Files:**
- Modify: `docs/superpowers/specs/2026-09-17-backtesting-design.md`
- Operations on the prod VM (`gcloud compute ssh varun@tradesmart-backend --zone asia-south1-a`, app at `/opt/tradesmart/app`)

- [ ] **Step 1: Amend the spec with this plan's five decisions**

In the spec's "2. Replay and candidate tape" section, replace the bullet that begins `- **What the tape depends on:**` so that `proximity_pct` is listed among the detector parameters and the sentence about applying any proximity afterwards is removed; add under "3. Signal study" the bullets: `- **Distinct setups:** the study counts the first fire of each setup identity; the report shows fires and setups.` and `- **Boundary:** a seen signal whose horizon reaches the split is excluded at that horizon.`; under "API → Worker loop" replace the stale-job sentence with `On start, every job in a running status is returned to queued (there is one worker).`; in "Migration 005" remove `stage,` from the column list. Commit:

```bash
git add docs/superpowers/specs/2026-09-17-backtesting-design.md
git commit -m "Record slice 2's decisions in the backtesting spec

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

- [ ] **Step 2: Suites green, scan, PR, merge**

```bash
cd backend && .venv/Scripts/python.exe -m pytest -q && cd ../frontend && npx vitest run && cd ..
git diff origin/main | grep -E "^\+" | grep -iE "csk-|gsk_|JWT_SECRET=[A-Za-z0-9]{8,}"; echo "scan exit $? (1 = clean)"
git push -u origin feature/backtesting-slice2
gh pr create --base main --title "Backtesting slice 2: replay and signal study" --body "<summary, decisions, test counts>

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
gh pr merge --merge && git checkout main && git pull
```

- [ ] **Step 3: Deploy both containers**

```bash
gcloud compute ssh varun@tradesmart-backend --zone asia-south1-a --command '
cd /opt/tradesmart/app && sudo git pull --ff-only -q && sudo git log --oneline -1 &&
sudo docker compose -f docker-compose.prod.yml build -q backend backtester &&
sudo docker compose -f docker-compose.prod.yml up -d backend backtester 2>&1 | tail -2 &&
sleep 40 && sudo docker compose -f docker-compose.prod.yml ps --format "{{.Service}} {{.Status}}" &&
sudo docker logs --tail 5 tradesmart-backtester'
```

Expected: both `healthy`; worker log shows `[worker] connected; schema up to date` and no traceback.

- [ ] **Step 4: Run a real backtest end to end**

Mint a session for a throwaway test wallet on the VM (never print it outside the VM) and submit a doji rule on BTCUSDT 1h:

```bash
gcloud compute ssh varun@tradesmart-backend --zone asia-south1-a --command '
TOKEN=$(sudo docker exec tradesmart-backend python -c "from services.auth_service import issue_token; print(issue_token(\"0x000000000000000000000000000000000000dead\")[\"token\"])")
curl -s -X POST https://api.vibetrading.club/api/backtests -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"rule\":{\"name\":\"doji\",\"symbol\":\"BTCUSDT\",\"timeframe\":\"1h\",\"params\":{\"agent\":\"sequence\",\"steps\":[{\"type\":\"candle\",\"shape\":\"doji\"}]}},\"neutral\":\"long\"}"'
```

Expected: `{"id":"…","status":"queued"}`. (`issue_token(owner_key)` returns `{token, address, expires_at}`; owner keys are lowercased addresses.) Poll `GET /api/backtests/<id>` the same way until `status` is `done`; expect `report.signals.setups` in the hundreds, both study periods present, `meta.replay_seconds` recorded. Then submit it again and expect `meta.tape_cached: true` within seconds. Delete both jobs with `DELETE`.

- [ ] **Step 5: Confirm live alerts were unaffected during the replay**

```bash
gcloud compute ssh varun@tradesmart-backend --zone asia-south1-a --command '
sudo docker logs --since 30m tradesmart-backend 2>&1 | grep -ciE "sweep failed";
sudo docker stats --no-stream --format "{{.Name}} {{.CPUPerc}} {{.MemUsage}}"'
```

Expected: `0`; backtester memory under 512 MiB.

- [ ] **Step 6: Browser check**

On `https://app.vibetrading.club/app`, signed in: Strategy → Armed → **Backtest** on a rule opens the sheet; run it; progress advances; the report renders the verdict and both tables. In chat, draft "alert me when a bullish engulfing forms" and press **Backtest** on the card.
