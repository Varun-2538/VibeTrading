# Indicator Triggers, Slice B: build them in the panel, see them in chat — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The eight triggers shipped in slice A become reachable without typing JSON or talking to the chat: a **Signal** rule type in the Strategy panel builds any one of them, the chat assistant can see them on the chart it is looking at, and its **Alert** button offers them.

**Architecture:** `analysis/scene.py` reports the new indicators compactly (the scene is token-budgeted, so each addition is a handful of numbers, not a series). `agents/fellow_subscribe.py` generalises its RSI-only indicator path into one that resolves any indicator finding to the matching rule step, reusing `describe_steps` for the summary. In the browser a new pure module, `lib/triggers.ts`, holds the catalogue of triggers with their fields and defaults, and the Strategy panel renders it as a third rule type that arms a one-step sequence rule.

**Tech Stack:** Python 3.11, numpy, pytest; Next.js 15, React 19, shadcn/ui, vitest.

**Spec:** the design agreed on 2026-09-22 and recorded in `docs/superpowers/plans/2026-09-22-indicator-triggers-slice-a.md`; slice A is live (eight step types, `MASK_STEPS`, `step_warmup`, `describe_steps`, `step_direction`).

## Global Constraints

- **The scene is a token budget, not a data dump.** It travels with every chat question on a free-tier model, so each indicator adds only what the model needs to speak and to mark: a current value, a state word, and at most two recent event times. The byte ceiling rises from 4,500 to 5,000 and the test keeps enforcing it; the measured scene is 4,369 bytes.
- **Nothing the detectors did not find may be marked.** New scene entries must expose their bar times so the grounding guard in `chart_fellow.ground()` can vouch for marks on them.
- **Alerts are built by the server from scene entries**, never from the model's words: the same rule as slice 5 of the chart fellow. A finding whose indicator has no rule step gets no Alert button.
- **The panel builds one-step sequence rules.** Multi-step chains stay in chat; a Signal rule is `{"agent": "sequence", "steps": [<one step>], "within_bars": 3, "lookback": <enough for the step>}`.
- Lookback in the browser must satisfy the server's `step_warmup` check, so `lib/triggers.ts` mirrors it and a test pins the two together by exercising the API's own error case.
- Commits end with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`; scan staged diffs for `csk-`, `gsk_`, `JWT_SECRET=`.

**Running tests.** Backend from `backend/`: `python -m pytest -q` (baseline **464**). Frontend from `frontend/`: `npx vitest run` (baseline **62**), `npx tsc --noEmit -p .` (only the pre-existing `tests/sw.test.ts` error), `npx next build`.

## File Structure

| File | Responsibility |
|---|---|
| Modify `backend/analysis/scene.py` | Stochastic, Bollinger (with squeeze), VWAP, volume and ATR in the scene; vocabulary. |
| Modify `backend/agents/fellow_subscribe.py` | One indicator resolver for all eight, replacing the RSI-only one. |
| Modify `backend/agents/chart_fellow.py` | One prompt line naming the new indicators. |
| Modify `backend/tests/test_scene.py`, `test_fellow_subscribe.py` | Tests, and the raised ceiling. |
| Create `frontend/lib/triggers.ts`, `frontend/tests/triggers.test.ts` | The trigger catalogue, pure. |
| Modify `frontend/components/analysis-panel.tsx` | The Signal rule type. |

---

### Task 1: The assistant can see them

**Files:** Modify `backend/analysis/scene.py`; Test `backend/tests/test_scene.py`

**Interfaces:**
- `_indicators(candles, places)` gains, each only when its warm-up is complete:
  - `stoch: {k, d, state: "overbought"|"oversold"|"middle", recent_crosses: [{level|"d", dir, t}] ≤2}`
  - `bollinger: {upper, lower, width, squeeze: bool, recent_crosses: [{band, dir, t}] ≤2}`
  - `vwap: {anchor: "day", value, side: "above"|"below", recent_crosses: [{dir, t}] ≤2}`
  - `volume: {ratio, spikes: [t] ≤2}`
  - `atr: {value, expansion: bool, recent: [t] ≤2}`
- `VOCABULARY["indicators"]` becomes `["rsi", "ema", "macd", "stochastic", "bollinger (and squeeze)", "vwap", "volume spike", "atr expansion"]`.
- `SCENE_BYTE_CEILING` in the test rises to `5_200`.

- [ ] **Step 1: Write the failing tests** (append to `backend/tests/test_scene.py`, and change `SCENE_BYTE_CEILING = 4_500` to `5_200`)

```python
def test_the_scene_reports_the_new_indicators():
    scene = build_scene(random_walk(n=400, seed=5), symbol="BTCUSDT", timeframe="1h")
    ind = scene["indicators"]
    assert set(ind) >= {"rsi", "ema", "macd", "stoch", "bollinger", "vwap", "volume", "atr"}

    assert 0 <= ind["stoch"]["k"] <= 100
    assert ind["stoch"]["state"] in ("overbought", "oversold", "middle")
    assert ind["bollinger"]["upper"] > ind["bollinger"]["lower"]
    assert isinstance(ind["bollinger"]["squeeze"], bool)
    assert ind["vwap"]["anchor"] == "day" and ind["vwap"]["side"] in ("above", "below")
    assert ind["volume"]["ratio"] > 0
    assert isinstance(ind["atr"]["expansion"], bool)


def test_new_indicator_events_carry_bar_times_the_guard_can_check():
    scene = build_scene(random_walk(n=400, seed=5), symbol="BTCUSDT", timeframe="1h")
    window = scene["window"]
    ind = scene["indicators"]
    times = (
        [c["t"] for c in ind["stoch"]["recent_crosses"]]
        + [c["t"] for c in ind["bollinger"]["recent_crosses"]]
        + [c["t"] for c in ind["vwap"]["recent_crosses"]]
        + list(ind["volume"]["spikes"])
        + list(ind["atr"]["recent"])
    )
    assert times, "no events at all in 400 random bars"
    for t in times:
        assert window["from"] <= t <= window["to"]


def test_the_new_indicators_are_capped():
    scene = build_scene(random_walk(n=1000, seed=11), symbol="BTCUSDT", timeframe="1h")
    ind = scene["indicators"]
    assert len(ind["stoch"]["recent_crosses"]) <= 2
    assert len(ind["bollinger"]["recent_crosses"]) <= 2
    assert len(ind["vwap"]["recent_crosses"]) <= 2
    assert len(ind["volume"]["spikes"]) <= 2
    assert len(ind["atr"]["recent"]) <= 2


def test_the_vocabulary_names_every_indicator_the_scene_can_report():
    scene = build_scene(random_walk(n=400, seed=5), symbol="BTCUSDT", timeframe="1h")
    said = " ".join(scene["vocabulary"]["indicators"])
    for word in ("rsi", "ema", "macd", "stochastic", "bollinger", "vwap", "volume", "atr"):
        assert word in said


def test_a_short_window_reports_only_what_warmed_up():
    scene = build_scene(random_walk(n=30, seed=5), symbol="BTCUSDT", timeframe="1h")
    # Nothing that needs 20 or more bars can be there; whatever is must be whole.
    for name, block in scene["indicators"].items():
        assert block, name
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_scene.py -q`
Expected: `KeyError: 'stoch'`.

- [ ] **Step 3: Implement** in `backend/analysis/scene.py`

Cap constant, next to the others:

```python
# Recent events per new indicator. Two is enough to say "again, and before
# that"; more is tokens for nothing.
MAX_INDICATOR_EVENTS = 2
```

Vocabulary:

```python
    "indicators": [
        "rsi", "ema", "macd", "stochastic", "bollinger (and squeeze)",
        "vwap", "volume spike", "atr expansion",
    ],
```

Then append to `_indicators`, before its `return out`:

```python
    highs = np.array([float(c["high"]) for c in candles], dtype=float)
    lows = np.array([float(c["low"]) for c in candles], dtype=float)
    volumes = np.array([float(c["volume"]) for c in candles], dtype=float)
    bar_times = np.array(times, dtype=np.int64)

    def recent(mask: np.ndarray) -> List[int]:
        """Bar times where `mask` is true inside the recent window, newest last."""
        if mask.size == 0:
            return []
        start = max(0, mask.size - RECENT_BARS)
        hits = [int(times[i]) for i in np.flatnonzero(mask[start:]) + start]
        return hits[-MAX_INDICATOR_EVENTS:]

    k_line, d_line = indicators.stochastic(highs, lows, closes)
    if not np.isnan(k_line[-1]):
        k_now = float(k_line[-1])
        stoch: Dict[str, Any] = {
            "k": _r(k_now, 1),
            "state": "overbought" if k_now >= 80 else "oversold" if k_now <= 20 else "middle",
            "recent_crosses": [],
        }
        if not np.isnan(d_line[-1]):
            stoch["d"] = _r(d_line[-1], 1)
            for direction in ("above", "below"):
                for t in recent(indicators.crosses_series(k_line, d_line, direction)):
                    stoch["recent_crosses"].append({"level": "d", "dir": direction, "t": t})
        for level in (20, 80):
            for direction in ("above", "below"):
                for t in recent(indicators.crosses(k_line, float(level), direction)):
                    stoch["recent_crosses"].append({"level": level, "dir": direction, "t": t})
        stoch["recent_crosses"] = sorted(stoch["recent_crosses"], key=lambda c: c["t"], reverse=True)[:MAX_INDICATOR_EVENTS]
        out["stoch"] = stoch

    middle, upper, lower, width = indicators.bollinger(closes)
    if not np.isnan(upper[-1]):
        tightest = indicators.rolling_min(width, 120)
        bands: Dict[str, Any] = {
            "upper": _r(upper[-1], places),
            "lower": _r(lower[-1], places),
            "width": _r(width[-1], 4),
            # The coiled-spring setup: bandwidth at its tightest in 120 bars.
            "squeeze": bool(not np.isnan(width[-1]) and width[-1] <= tightest[-1]),
            "recent_crosses": [],
        }
        for band, series in (("upper", upper), ("lower", lower)):
            for direction in ("above", "below"):
                for t in recent(indicators.crosses_series(closes, series, direction)):
                    bands["recent_crosses"].append({"band": band, "dir": direction, "t": t})
        bands["recent_crosses"] = sorted(bands["recent_crosses"], key=lambda c: c["t"], reverse=True)[:MAX_INDICATOR_EVENTS]
        out["bollinger"] = bands

    vwap_line = indicators.vwap(highs, lows, closes, volumes, bar_times, anchor="day")
    if not np.isnan(vwap_line[-1]):
        vwap_block: Dict[str, Any] = {
            "anchor": "day",
            "value": _r(vwap_line[-1], places),
            "side": "above" if closes[-1] >= vwap_line[-1] else "below",
            "recent_crosses": [],
        }
        for direction in ("above", "below"):
            for t in recent(indicators.crosses_series(closes, vwap_line, direction)):
                vwap_block["recent_crosses"].append({"dir": direction, "t": t})
        vwap_block["recent_crosses"] = sorted(vwap_block["recent_crosses"], key=lambda c: c["t"], reverse=True)[:MAX_INDICATOR_EVENTS]
        out["vwap"] = vwap_block

    ratio = indicators.volume_ratio(volumes)
    if not np.isnan(ratio[-1]):
        with np.errstate(invalid="ignore"):
            spikes = np.nan_to_num(ratio, nan=0.0) >= 2.0
        out["volume"] = {"ratio": _r(ratio[-1], 2), "spikes": recent(spikes)}

    ranges = indicators.true_range(highs, lows, closes)
    unit = indicators.atr_series(highs, lows, closes)
    if not np.isnan(unit[-1]):
        with np.errstate(invalid="ignore"):
            wide = np.nan_to_num(ranges, nan=0.0) >= 2.0 * np.nan_to_num(unit, nan=np.inf)
        out["atr"] = {
            "value": _r(unit[-1], places),
            "expansion": bool(wide[-1]),
            "recent": recent(wide),
        }
```

Add `List` to the module's `typing` import if it is not already there.

- [ ] **Step 4: Run to verify they pass, and see the size**

Run: `python -m pytest tests/test_scene.py -q`
Expected: all passed. Then print the size to know the real headroom:

```bash
python -c "
import sys; sys.path.insert(0,'tests')
import json
from analysis.scene import build_scene
from walks import random_walk
s = build_scene(random_walk(1000, seed=11), symbol='BTCUSDT', timeframe='1h')
print(len(json.dumps(s, separators=(',',':'))), 'bytes')"
```

If it exceeds 5,200, cut `MAX_INDICATOR_EVENTS` to 1 rather than raising the ceiling again: the ceiling exists because the scene rides on every question.

- [ ] **Step 5: Commit**

```bash
git add backend/analysis/scene.py backend/tests/test_scene.py
git commit -m "Report stochastic, Bollinger, VWAP, volume and ATR in the scene

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: The guard can vouch for their marks

**Files:** Modify `backend/agents/chart_fellow.py`; Test `backend/tests/test_chart_fellow.py` (append)

**Interfaces:** `_scene_times` includes the new indicators' event times, and `_scene_prices` includes the Bollinger bands and the VWAP value, so a mark on them survives the guard. One prompt line names the new indicators.

- [ ] **Step 1: Write the failing tests** (append)

```python
def test_marks_on_the_new_indicators_survive_the_guard():
    scene = dict(SCENE)
    scene["indicators"] = {
        **SCENE["indicators"],
        "bollinger": {"upper": 62_100.0, "lower": 59_900.0, "width": 0.03, "squeeze": True,
                      "recent_crosses": [{"band": "upper", "dir": "above", "t": T0 + 96 * H}]},
        "vwap": {"anchor": "day", "value": 60_750.0, "side": "above",
                 "recent_crosses": [{"dir": "above", "t": T0 + 95 * H}]},
        "volume": {"ratio": 3.1, "spikes": [T0 + 94 * H]},
        "atr": {"value": 300.0, "expansion": True, "recent": [T0 + 93 * H]},
        "stoch": {"k": 85.0, "d": 70.0, "state": "overbought",
                  "recent_crosses": [{"level": "d", "dir": "above", "t": T0 + 92 * H}]},
    }
    answer = parse_answer(json.dumps({
        "reply_md": "Bands, VWAP and a volume spike.",
        "findings": [
            {"kind": "indicator", "label": "upper band", "present": True,
             "marks": [{"type": "hline", "price": 62_100.0},
                       {"type": "bar", "time": T0 + 96 * H}]},
            {"kind": "indicator", "label": "VWAP", "present": True,
             "marks": [{"type": "hline", "price": 60_750.0}]},
            {"kind": "indicator", "label": "volume spike", "present": True,
             "marks": [{"type": "bar", "time": T0 + 94 * H}]},
            {"kind": "indicator", "label": "range expansion", "present": True,
             "marks": [{"type": "bar", "time": T0 + 93 * H}]},
            {"kind": "indicator", "label": "stochastic cross", "present": True,
             "marks": [{"type": "bar", "time": T0 + 92 * H}]},
        ],
    }), scene)
    assert all(f.grounded for f in answer.findings), [f.label for f in answer.findings if not f.grounded]
    assert sum(len(f.marks) for f in answer.findings) == 6


def test_a_band_price_that_is_not_in_the_scene_is_still_dropped():
    scene = dict(SCENE)
    scene["indicators"] = {**SCENE["indicators"],
                           "bollinger": {"upper": 62_100.0, "lower": 59_900.0, "width": 0.03,
                                         "squeeze": False, "recent_crosses": []}}
    answer = parse_answer(json.dumps({
        "reply_md": "Invented band.",
        "findings": [{"kind": "indicator", "label": "upper band", "present": True,
                      "marks": [{"type": "hline", "price": 61_234.0}]}],
    }), scene)
    assert answer.findings[0].marks == [] and not answer.findings[0].grounded


def test_the_prompt_names_the_new_indicators():
    from agents.chart_fellow import SYSTEM_PROMPT

    for word in ("stochastic", "Bollinger", "squeeze", "VWAP", "volume", "ATR"):
        assert word.lower() in SYSTEM_PROMPT.lower(), word
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_chart_fellow.py -q`
Expected: the grounding test fails (bands and event times are not in the scene's price and time sets), and the prompt test fails.

- [ ] **Step 3: Implement** in `backend/agents/chart_fellow.py`

In `_scene_prices`, after the EMA block:

```python
    bands = scene.get("indicators", {}).get("bollinger") or {}
    prices += [float(bands[k]) for k in ("upper", "lower") if bands.get(k) is not None]
    vwap_block = scene.get("indicators", {}).get("vwap") or {}
    if vwap_block.get("value") is not None:
        prices.append(float(vwap_block["value"]))
```

In `_scene_times`, after the existing indicator loop:

```python
    for name in ("stoch", "bollinger", "vwap"):
        for cross in ind.get(name, {}).get("recent_crosses", []):
            times.add(int(cross["t"]))
    times.update(int(t) for t in ind.get("volume", {}).get("spikes", []))
    times.update(int(t) for t in ind.get("atr", {}).get("recent", []))
```

In `SYSTEM_PROMPT`, extend the line about what the scene holds with:

```
- Indicators in the scene are RSI, EMA, MACD, stochastic (with its %D and 20/80 crosses), Bollinger bands (with a squeeze flag when bandwidth is at its tightest), session VWAP, volume spikes against the recent average, and ATR range expansion. Mark a band or VWAP with an hline at the exact price given, and a cross, spike or expansion with a bar mark at the bar time given.
```

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_chart_fellow.py -q`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add backend/agents/chart_fellow.py backend/tests/test_chart_fellow.py
git commit -m "Let the guard vouch for marks on the new indicators

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Alert on any of them

**Files:** Modify `backend/agents/fellow_subscribe.py`; Test `backend/tests/test_fellow_subscribe.py`

**Interfaces:** `_indicator_step(finding, scene) -> Optional[Dict]` replaces `_rsi_cross`, returning the rule step for whichever indicator the finding points at — resolved first from the bar times or prices it marked, then from its label, and only ever against entries the scene actually holds. `_draft`'s `indicator` branch uses it, with `describe_steps([step])` for the summary.

- [ ] **Step 1: Write the failing tests** (append; the existing RSI tests must keep passing unchanged)

```python
def scene_with(**indicators):
    scene = copy.deepcopy(SCENE)
    scene["indicators"] = {**scene["indicators"], **indicators}
    return scene


def test_an_ema_cross_finding_becomes_an_ema_step():
    scene = scene_with(ema={"20": 60_900.0, "50": 60_400.0, "stack": "bullish",
                            "recent_cross": {"dir": "bullish", "t": T0 + 96 * H}})
    sub = subscription_for(finding("indicator", "EMA 20/50 cross", [{"type": "bar", "time": T0 + 96 * H}]), scene)
    assert_armable(sub)
    assert sub.draft["params"]["steps"] == [
        {"type": "ema_cross", "fast": 20, "slow": 50, "cross": "above"}
    ]
    assert "EMA(20) crosses above EMA(50)" in sub.summary


def test_a_macd_finding_becomes_a_macd_step():
    scene = scene_with(macd={"line": 10.0, "signal": 8.0, "hist": 2.0,
                             "recent_cross": {"dir": "bearish", "t": T0 + 95 * H}})
    sub = subscription_for(finding("indicator", "MACD cross", [{"type": "bar", "time": T0 + 95 * H}]), scene)
    assert sub.draft["params"]["steps"] == [
        {"type": "macd_cross", "fast": 12, "slow": 26, "signal": 9, "against": "signal", "cross": "below"}
    ]


def test_a_stochastic_finding_reads_its_own_cross():
    scene = scene_with(stoch={"k": 25.0, "d": 20.0, "state": "oversold",
                              "recent_crosses": [{"level": 20, "dir": "above", "t": T0 + 94 * H}]})
    sub = subscription_for(finding("indicator", "stochastic", [{"type": "bar", "time": T0 + 94 * H}]), scene)
    step = sub.draft["params"]["steps"][0]
    assert step["type"] == "stoch_cross" and step["against"] == "level" and step["level"] == 20.0


def test_a_band_finding_becomes_a_bollinger_step_and_a_squeeze_becomes_a_squeeze_step():
    scene = scene_with(bollinger={"upper": 62_500.0, "lower": 59_900.0, "width": 0.03, "squeeze": True,
                                  "recent_crosses": [{"band": "upper", "dir": "above", "t": T0 + 93 * H}]})
    band = subscription_for(finding("indicator", "upper Bollinger band", [{"type": "hline", "price": 62_500.0}]), scene)
    assert band.draft["params"]["steps"][0] == {
        "type": "bollinger", "band": "upper", "cross": "above", "period": 20, "std": 2.0
    }
    squeeze = subscription_for(finding("indicator", "Bollinger squeeze"), scene)
    assert squeeze.draft["params"]["steps"][0]["type"] == "bollinger_squeeze"


def test_a_vwap_finding_keeps_the_anchor_and_watches_the_side_it_is_not_on():
    # Marking the VWAP line says "this line matters", not which way. The event
    # worth an alert is the crossing away from where price already sits: above
    # VWAP, that is losing it; below it, reclaiming it.
    above = scene_with(vwap={"anchor": "day", "value": 60_750.0, "side": "above", "recent_crosses": []})
    sub = subscription_for(finding("indicator", "VWAP", [{"type": "hline", "price": 60_750.0}]), above)
    assert sub.draft["params"]["steps"][0] == {"type": "vwap_cross", "anchor": "day", "cross": "below"}

    below = scene_with(vwap={"anchor": "week", "value": 60_750.0, "side": "below", "recent_crosses": []})
    reclaim = subscription_for(finding("indicator", "VWAP", [{"type": "hline", "price": 60_750.0}]), below)
    assert reclaim.draft["params"]["steps"][0] == {"type": "vwap_cross", "anchor": "week", "cross": "above"}

    # A marked cross still wins: it says which way it went.
    crossed = scene_with(vwap={"anchor": "day", "value": 60_750.0, "side": "above",
                               "recent_crosses": [{"dir": "above", "t": T0 + 92 * H}]})
    marked = subscription_for(finding("indicator", "VWAP", [{"type": "bar", "time": T0 + 92 * H}]), crossed)
    assert marked.draft["params"]["steps"][0]["cross"] == "above"


def test_volume_and_range_findings_become_their_steps():
    scene = scene_with(volume={"ratio": 3.2, "spikes": [T0 + 91 * H]},
                       atr={"value": 300.0, "expansion": True, "recent": [T0 + 90 * H]})
    volume = subscription_for(finding("indicator", "volume spike", [{"type": "bar", "time": T0 + 91 * H}]), scene)
    assert volume.draft["params"]["steps"][0]["type"] == "volume_spike"
    atr = subscription_for(finding("indicator", "range expansion", [{"type": "bar", "time": T0 + 90 * H}]), scene)
    assert atr.draft["params"]["steps"][0]["type"] == "atr_expansion"


def test_an_indicator_the_scene_does_not_hold_gets_no_alert():
    # The scene has no stochastic at all, so a stochastic finding is not armable.
    assert subscription_for(finding("indicator", "stochastic cross"), SCENE) is None


def test_the_lookback_is_long_enough_for_the_step_it_builds():
    scene = scene_with(bollinger={"upper": 62_500.0, "lower": 59_900.0, "width": 0.03, "squeeze": True,
                                  "recent_crosses": []})
    sub = subscription_for(finding("indicator", "Bollinger squeeze"), scene)
    # RuleCreate refuses a lookback that cannot cover a 120-bar squeeze.
    assert_armable(sub)
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_backtest_tuning.py -q` → unaffected; `python -m pytest tests/test_fellow_subscribe.py -q`
Expected: the new tests fail — `_rsi_cross` only knows RSI, so these findings resolve to nothing.

- [ ] **Step 3: Implement** in `backend/agents/fellow_subscribe.py`

Replace `_rsi_cross` with:

```python
# The indicator a label is talking about, when it marked nothing usable.
INDICATOR_WORDS = (
    ("rsi", ("rsi",)),
    ("ema", ("ema", "moving average", "golden cross", "death cross")),
    ("macd", ("macd",)),
    ("stoch", ("stoch",)),
    ("bollinger_squeeze", ("squeeze", "coil", "tightening")),
    ("bollinger", ("bollinger", "band")),
    ("vwap", ("vwap",)),
    ("volume", ("volume",)),
    ("atr", ("atr", "range expansion", "wide bar", "volatility")),
)


def _named_indicator(label: str) -> Optional[str]:
    text = _norm(label)
    for name, words in INDICATOR_WORDS:
        if any(word in text for word in words):
            return name
    return None


def _indicator_step(finding: Finding, scene: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    The rule step an indicator finding subscribes to.

    Resolved from what the finding marked where possible - a bar time or a
    price the scene reported - and from its label otherwise, but only ever
    against an indicator the scene actually holds. An indicator the detectors
    did not report cannot be alerted on, however confidently the model named it.
    """
    ind = scene.get("indicators") or {}
    times = set(_bar_times(finding))
    prices = _line_prices(finding)

    rsi = ind.get("rsi") or {}
    for cross in rsi.get("recent_crosses") or []:
        if int(cross["t"]) in times:
            return {"type": "indicator", "indicator": "rsi", "period": int(rsi.get("period", 14)),
                    "cross": cross["dir"], "level": float(cross["level"])}

    ema = ind.get("ema") or {}
    cross = ema.get("recent_cross")
    if cross and int(cross["t"]) in times:
        return {"type": "ema_cross", "fast": 20, "slow": 50,
                "cross": "above" if cross["dir"] == "bullish" else "below"}

    macd = ind.get("macd") or {}
    cross = macd.get("recent_cross")
    if cross and int(cross["t"]) in times:
        return {"type": "macd_cross", "fast": 12, "slow": 26, "signal": 9, "against": "signal",
                "cross": "above" if cross["dir"] == "bullish" else "below"}

    stoch = ind.get("stoch") or {}
    for cross in stoch.get("recent_crosses") or []:
        if int(cross["t"]) in times:
            if cross["level"] == "d":
                return {"type": "stoch_cross", "against": "d", "cross": cross["dir"]}
            return {"type": "stoch_cross", "against": "level", "level": float(cross["level"]),
                    "cross": cross["dir"]}

    bands = ind.get("bollinger") or {}
    for cross in bands.get("recent_crosses") or []:
        if int(cross["t"]) in times:
            return {"type": "bollinger", "band": cross["band"], "cross": cross["dir"],
                    "period": 20, "std": 2.0}
    for band in ("upper", "lower"):
        if bands.get(band) is not None and any(_near(p, float(bands[band])) for p in prices):
            return {"type": "bollinger", "band": band,
                    "cross": "above" if band == "upper" else "below", "period": 20, "std": 2.0}

    vwap = ind.get("vwap") or {}
    if vwap:
        for cross in vwap.get("recent_crosses") or []:
            if int(cross["t"]) in times:
                return {"type": "vwap_cross", "anchor": vwap.get("anchor", "day"), "cross": cross["dir"]}
        if vwap.get("value") is not None and any(_near(p, float(vwap["value"])) for p in prices):
            return {"type": "vwap_cross", "anchor": vwap.get("anchor", "day"), "cross": "above"}

    volume = ind.get("volume") or {}
    if any(int(t) in times for t in volume.get("spikes") or []):
        return {"type": "volume_spike", "multiple": 2.0, "period": 20}

    atr = ind.get("atr") or {}
    if any(int(t) in times for t in atr.get("recent") or []):
        return {"type": "atr_expansion", "multiple": 2.0, "period": 14}

    # Nothing matched what it marked; fall back to the words, still requiring
    # the scene to hold that indicator.
    named = _named_indicator(finding.label)
    if named == "rsi" and rsi.get("recent_crosses"):
        first = rsi["recent_crosses"][0]
        return {"type": "indicator", "indicator": "rsi", "period": int(rsi.get("period", 14)),
                "cross": first["dir"], "level": float(first["level"])}
    if named == "ema" and ema:
        direction = ema.get("recent_cross", {}).get("dir") or ema.get("stack") or "bullish"
        return {"type": "ema_cross", "fast": 20, "slow": 50,
                "cross": "above" if direction == "bullish" else "below"}
    if named == "macd" and macd:
        direction = macd.get("recent_cross", {}).get("dir", "bullish")
        return {"type": "macd_cross", "fast": 12, "slow": 26, "signal": 9, "against": "signal",
                "cross": "above" if direction == "bullish" else "below"}
    if named == "stoch" and stoch:
        state = stoch.get("state")
        if state == "overbought":
            return {"type": "stoch_cross", "against": "level", "level": 80.0, "cross": "below"}
        return {"type": "stoch_cross", "against": "level", "level": 20.0, "cross": "above"}
    if named == "bollinger_squeeze" and bands:
        return {"type": "bollinger_squeeze", "period": 20, "std": 2.0, "lookback": 120}
    if named == "bollinger" and bands:
        return {"type": "bollinger", "band": "upper", "cross": "above", "period": 20, "std": 2.0}
    if named == "vwap" and vwap:
        return {"type": "vwap_cross", "anchor": vwap.get("anchor", "day"), "cross": "above"}
    if named == "volume" and volume:
        return {"type": "volume_spike", "multiple": 2.0, "period": 20}
    if named == "atr" and atr:
        return {"type": "atr_expansion", "multiple": 2.0, "period": 14}
    return None
```

Replace the `indicator` branch of `_draft` with:

```python
    if finding.kind == "indicator":
        step = _indicator_step(finding, scene)
        if not step:
            return None
        said = describe_steps([step])
        return {
            "name": f"{symbol} {said}",
            "params": _sequence([step]),
            "summary": f"Alert when {said} on {where}",
        }
```

and give `_sequence` a lookback long enough for whatever step it holds:

```python
def _sequence(steps: List[Dict[str, Any]]) -> Dict[str, Any]:
    # A squeeze needs its whole window plus the Bollinger period; the schema
    # refuses a lookback that cannot cover the step, so compute it here.
    needed = max(step_warmup(s) for s in steps) + 3 * len(steps) + 2
    return {"agent": "sequence", "steps": steps, "lookback": max(300, needed)}
```

Import `step_warmup` from `models.rule_schemas` and `describe_steps` from `analysis.sequence` at the top of the file.

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_fellow_subscribe.py -q`
Expected: all passed, the earlier RSI tests included.

- [ ] **Step 5: Commit**

```bash
git add backend/agents/fellow_subscribe.py backend/tests/test_fellow_subscribe.py
git commit -m "Offer an alert for any indicator the assistant can see

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: The trigger catalogue in the browser

**Files:** Create `frontend/lib/triggers.ts`, `frontend/tests/triggers.test.ts`

**Interfaces:**
- `TriggerField = { key: string; label: string; kind: "number" | "choice"; step?: number; min?: number; max?: number; choices?: { value: string; label: string }[] }`
- `TriggerDef = { id: string; label: string; group: "Indicators" | "Candles" | "Structure"; fields: TriggerField[]; defaults: Record<string, string | number>; build: (values: Record<string, string | number>) => SequenceStep }`
- `TRIGGERS: TriggerDef[]` — the eight new triggers, RSI, the six candle shapes as one trigger with a shape choice, and the four structure events as one with event and side choices.
- `triggerById(id) -> TriggerDef | undefined`
- `stepWarmup(step: SequenceStep) -> number` — mirrors the server's `step_warmup`.
- `signalParams(def, values) -> SequenceRuleParams` — a one-step sequence with `within_bars: 3` and a lookback that covers the step. The panel already funnels every rule type through one `createRule` call, so a Signal rule only needs its params.
- `triggerName(def, values) -> string` — the rule's default name.

- [ ] **Step 1: Write the failing tests** — `frontend/tests/triggers.test.ts`:

```ts
import { describe, expect, it } from "vitest"

import { TRIGGERS, signalParams, stepWarmup, triggerById, triggerName } from "@/lib/triggers"

describe("the trigger catalogue", () => {
  it("covers every step type the server knows", () => {
    expect(TRIGGERS.map((t) => t.id).sort()).toEqual([
      "atr_expansion", "bollinger", "bollinger_squeeze", "candle", "ema_cross",
      "macd_cross", "rsi", "stoch_cross", "structure", "vwap_cross", "volume_spike",
    ].sort())
  })

  it("builds each trigger from its own defaults", () => {
    for (const def of TRIGGERS) {
      const step = def.build(def.defaults)
      expect(step.type).toBeTruthy()
      expect(stepWarmup(step)).toBeGreaterThan(0)
    }
  })

  it("builds an EMA cross with the values given", () => {
    const def = triggerById("ema_cross")!
    expect(def.build({ ...def.defaults, fast: 50, slow: 200, cross: "below" })).toEqual({
      type: "ema_cross", fast: 50, slow: 200, cross: "below",
    })
  })

  it("mirrors the server's warm-up arithmetic", () => {
    expect(stepWarmup({ type: "ema_cross", fast: 20, slow: 50, cross: "above" })).toBe(50)
    expect(stepWarmup({ type: "macd_cross", fast: 12, slow: 26, signal: 9, against: "signal", cross: "above" })).toBe(35)
    expect(stepWarmup({ type: "bollinger_squeeze", period: 20, lookback: 120 })).toBe(140)
    expect(stepWarmup({ type: "candle", shape: "doji" })).toBe(2)
  })

  it("asks for a lookback long enough for the step", () => {
    const squeeze = triggerById("bollinger_squeeze")!
    const params = signalParams(squeeze, squeeze.defaults)
    expect(params.agent).toBe("sequence")
    expect(params.lookback!).toBeGreaterThanOrEqual(140 + 3 + 2)
    expect(params.steps).toHaveLength(1)
    expect(params.within_bars).toBe(3)
  })

  it("names a rule after what it watches", () => {
    const def = triggerById("vwap_cross")!
    expect(triggerName(def, { ...def.defaults, anchor: "week", cross: "above" })).toBe("VWAP cross")
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `npx vitest run tests/triggers.test.ts`
Expected: cannot resolve `@/lib/triggers`.

- [ ] **Step 3: Implement** — `frontend/lib/triggers.ts`:

```ts
import type { SequenceRuleParams, SequenceStep } from "@/lib/rules"

/**
 * What the Strategy panel can build as a one-step rule.
 *
 * One entry per step type the server accepts, with its fields, its defaults
 * and how to turn the field values into a step. Keeping it as data means the
 * panel renders whatever is here without a branch per trigger, and the same
 * catalogue can label a rule someone else built.
 */
export interface TriggerField {
  key: string
  label: string
  kind: "number" | "choice"
  step?: number
  min?: number
  max?: number
  choices?: { value: string; label: string }[]
}

export interface TriggerDef {
  id: string
  label: string
  group: "Indicators" | "Candles" | "Structure"
  fields: TriggerField[]
  defaults: Record<string, string | number>
  build: (values: Record<string, string | number>) => SequenceStep
}

const CROSS: TriggerField = {
  key: "cross",
  label: "Direction",
  kind: "choice",
  choices: [
    { value: "above", label: "crosses above" },
    { value: "below", label: "crosses below" },
  ],
}

const num = (key: string, label: string, step = 1, min = 1, max = 400): TriggerField => ({
  key, label, kind: "number", step, min, max,
})

export const TRIGGERS: TriggerDef[] = [
  {
    id: "ema_cross",
    label: "EMA cross",
    group: "Indicators",
    fields: [num("fast", "Fast EMA (1 = price)"), num("slow", "Slow EMA"), CROSS],
    defaults: { fast: 20, slow: 50, cross: "above" },
    build: (v) => ({ type: "ema_cross", fast: Number(v.fast), slow: Number(v.slow), cross: v.cross as "above" | "below" }),
  },
  {
    id: "macd_cross",
    label: "MACD cross",
    group: "Indicators",
    fields: [
      { key: "against", label: "Against", kind: "choice", choices: [
        { value: "signal", label: "its signal line" }, { value: "zero", label: "zero" }] },
      CROSS,
    ],
    defaults: { against: "signal", cross: "above" },
    build: (v) => ({ type: "macd_cross", fast: 12, slow: 26, signal: 9, against: v.against as "signal" | "zero", cross: v.cross as "above" | "below" }),
  },
  {
    id: "rsi",
    label: "RSI level",
    group: "Indicators",
    fields: [num("period", "Period", 1, 2, 200), num("level", "Level", 1, 0, 100), CROSS],
    defaults: { period: 14, level: 30, cross: "above" },
    build: (v) => ({ type: "indicator", indicator: "rsi", period: Number(v.period), level: Number(v.level), cross: v.cross as "above" | "below" }),
  },
  {
    id: "stoch_cross",
    label: "Stochastic",
    group: "Indicators",
    fields: [
      { key: "against", label: "Against", kind: "choice", choices: [
        { value: "d", label: "its %D line" }, { value: "level", label: "a level" }] },
      num("level", "Level", 1, 0, 100),
      CROSS,
    ],
    defaults: { against: "level", level: 20, cross: "above" },
    build: (v) => ({ type: "stoch_cross", k: 14, k_smooth: 3, d: 3, against: v.against as "d" | "level", level: Number(v.level), cross: v.cross as "above" | "below" }),
  },
  {
    id: "bollinger",
    label: "Bollinger band",
    group: "Indicators",
    fields: [
      { key: "band", label: "Band", kind: "choice", choices: [
        { value: "upper", label: "upper" }, { value: "middle", label: "middle" }, { value: "lower", label: "lower" }] },
      CROSS,
      num("period", "Period", 1, 2, 400),
    ],
    defaults: { band: "upper", cross: "above", period: 20 },
    build: (v) => ({ type: "bollinger", band: v.band as "upper" | "middle" | "lower", cross: v.cross as "above" | "below", period: Number(v.period), std: 2 }),
  },
  {
    id: "bollinger_squeeze",
    label: "Bollinger squeeze",
    group: "Indicators",
    fields: [num("period", "Period", 1, 2, 400), num("lookback", "Tightest in (bars)", 10, 10, 1000)],
    defaults: { period: 20, lookback: 120 },
    build: (v) => ({ type: "bollinger_squeeze", period: Number(v.period), std: 2, lookback: Number(v.lookback) }),
  },
  {
    id: "vwap_cross",
    label: "VWAP cross",
    group: "Indicators",
    fields: [
      { key: "anchor", label: "Anchored to", kind: "choice", choices: [
        { value: "day", label: "the UTC day" }, { value: "week", label: "the week" }] },
      CROSS,
    ],
    defaults: { anchor: "day", cross: "above" },
    build: (v) => ({ type: "vwap_cross", anchor: v.anchor as "day" | "week", cross: v.cross as "above" | "below" }),
  },
  {
    id: "volume_spike",
    label: "Volume spike",
    group: "Indicators",
    fields: [num("multiple", "Times its average", 0.5, 1.1, 50), num("period", "Average over", 1, 2, 400)],
    defaults: { multiple: 2, period: 20 },
    build: (v) => ({ type: "volume_spike", multiple: Number(v.multiple), period: Number(v.period) }),
  },
  {
    id: "atr_expansion",
    label: "Range expansion",
    group: "Indicators",
    fields: [num("multiple", "Times ATR", 0.5, 1.1, 20), num("period", "ATR period", 1, 2, 200)],
    defaults: { multiple: 2, period: 14 },
    build: (v) => ({ type: "atr_expansion", multiple: Number(v.multiple), period: Number(v.period) }),
  },
  {
    id: "candle",
    label: "Candle shape",
    group: "Candles",
    fields: [
      { key: "shape", label: "Shape", kind: "choice", choices: [
        { value: "doji", label: "doji" },
        { value: "hammer", label: "hammer" },
        { value: "shooting_star", label: "shooting star" },
        { value: "bullish_engulfing", label: "bullish engulfing" },
        { value: "bearish_engulfing", label: "bearish engulfing" },
        { value: "inside_bar", label: "inside bar" }] },
    ],
    defaults: { shape: "doji" },
    build: (v) => ({ type: "candle", shape: v.shape as "doji" }),
  },
  {
    id: "structure",
    label: "Structure event",
    group: "Structure",
    fields: [
      { key: "event", label: "Event", kind: "choice", choices: [
        { value: "sweep", label: "liquidity sweep" },
        { value: "breakout", label: "breakout" },
        { value: "rejection", label: "rejection" },
        { value: "pullback", label: "pullback" }] },
      { key: "side", label: "Side", kind: "choice", choices: [
        { value: "bullish", label: "bullish" }, { value: "bearish", label: "bearish" }] },
    ],
    defaults: { event: "sweep", side: "bullish" },
    build: (v) => ({ type: "structure", event: v.event as "sweep", side: v.side as "bullish" | "bearish" }),
  },
]

export function triggerById(id: string): TriggerDef | undefined {
  return TRIGGERS.find((t) => t.id === id)
}

/**
 * Bars a step needs before it can be judged, mirroring the server's
 * step_warmup. The server refuses a rule whose lookback cannot cover its
 * step, and a refusal the user could not have avoided is a bug here.
 */
export function stepWarmup(step: SequenceStep): number {
  switch (step.type) {
    case "indicator":
      return (step.period ?? 14) + 1
    case "ema_cross":
      return step.slow
    case "macd_cross":
      return (step.slow ?? 26) + (step.signal ?? 9)
    case "stoch_cross":
      return (step.k ?? 14) + (step.k_smooth ?? 3) + (step.d ?? 3)
    case "bollinger":
      return step.period ?? 20
    case "bollinger_squeeze":
      return (step.period ?? 20) + (step.lookback ?? 120)
    case "volume_spike":
      return (step.period ?? 20) + 1
    case "atr_expansion":
      return (step.period ?? 14) + 2
    default:
      return 2
  }
}

export function triggerName(def: TriggerDef, values: Record<string, string | number>): string {
  if (def.id === "candle") return String(values.shape).replace(/_/g, " ")
  if (def.id === "structure") return `${values.side} ${values.event}`
  return def.label
}

/** The params of a one-step sequence rule for this trigger. */
export function signalParams(
  def: TriggerDef,
  values: Record<string, string | number>,
): SequenceRuleParams {
  const step = def.build(values)
  const within = 3
  return {
    agent: "sequence",
    steps: [step],
    within_bars: within,
    lookback: Math.max(300, stepWarmup(step) + within + 2),
  }
}
```

- [ ] **Step 4: Run to verify they pass**

Run: `npx vitest run tests/triggers.test.ts` — 6 passed; `npx tsc --noEmit -p .` — only the pre-existing error.

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/triggers.ts frontend/tests/triggers.test.ts
git commit -m "A catalogue of the triggers the panel can build

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: The Signal rule type in the panel

**Files:** Modify `frontend/components/analysis-panel.tsx`

**Interfaces:** The Build tab's rule-type select gains **Signal**. Choosing it shows a trigger select (grouped by Indicators, Candles, Structure) and the chosen trigger's fields, rendered from `TRIGGERS`. Arm goes through the panel's existing `createRule` call, with `params` from `signalParams` and `persist_bars: 0`. Pattern and liquidity are untouched.

- [ ] **Step 1: Implement**

The panel derives `params` and `defaultName` in two `useMemo`s and arms through a single
`createRule` call, so a Signal rule is a third branch in each - not a second code path.

1. Extend the imports:
   ```tsx
   import { SelectGroup, SelectLabel } from "@/components/ui/select"   // add to the existing select import
   import { TRIGGERS, signalParams, triggerById, triggerName } from "@/lib/triggers"
   ```
2. The panel's rule-type union gains a UI-only member, because the server has no `signal`
   agent - a Signal rule is a sequence rule:
   ```tsx
   type BuildKind = RuleAgent | "signal"
   ```
   and `const [agent, setAgent] = useState<RuleAgent>("pattern")` becomes
   `const [agent, setAgent] = useState<BuildKind>("pattern")`.
3. Trigger state, beside the other build fields:
   ```tsx
   const [triggerId, setTriggerId] = useState(TRIGGERS[0].id)
   const [triggerValues, setTriggerValues] = useState<Record<string, string | number>>(TRIGGERS[0].defaults)

   function chooseTrigger(id: string) {
     const def = triggerById(id)
     setTriggerId(id)
     setTriggerValues(def ? { ...def.defaults } : {})
   }
   ```
4. In the `params` memo, before the `pattern` branch:
   ```tsx
     if (agent === "signal") {
       const def = triggerById(triggerId)
       if (def) return signalParams(def, triggerValues)
     }
   ```
   and add `triggerId, triggerValues` to its dependency array.
5. In the `defaultName` memo, before the `pattern` branch:
   ```tsx
     if (agent === "signal") {
       const def = triggerById(triggerId)
       if (def) return `${symbol} ${triggerName(def, triggerValues)}`
     }
   ```
   and add `triggerId, triggerValues` to its dependency array.
6. In `handleArm`, the persistence line becomes:
   ```tsx
         // A pattern must hold for one further close before it counts, which is
         // what stops one that repaints away from raising an alert. A sequence
         // step is settled at the close, so it needs no such wait.
         persist_bars: agent === "signal" ? 0 : 1,
   ```
7. The Build tab currently reads `{agent === "pattern" ? (` … `) : (` … `)}` (lines 437, 516
   and 586). Replace the opening `{agent === "pattern" ? (` with `{agent === "pattern" && (`,
   replace the `) : (` at 516 with `)}\n            {agent === "liquidity" && (`, and leave the
   closing `)}`. The two field groups are then independent, and neither shows for a Signal rule.
8. After the liquidity group's closing `)}`, add the Signal fields:
   ```tsx
            {agent === "signal" && (
              <>
                <div className="flex flex-col gap-1">
                  <label className="text-[10px] uppercase tracking-wide text-muted-foreground">
                    Trigger
                  </label>
                  <Select value={triggerId} onValueChange={chooseTrigger}>
                    <SelectTrigger className={cn(FIELD, "w-[150px]")}>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {["Indicators", "Candles", "Structure"].map((group) => (
                        <SelectGroup key={group}>
                          <SelectLabel className="text-[10px]">{group}</SelectLabel>
                          {TRIGGERS.filter((t) => t.group === group).map((t) => (
                            <SelectItem key={t.id} value={t.id}>
                              {t.label}
                            </SelectItem>
                          ))}
                        </SelectGroup>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                {(triggerById(triggerId)?.fields ?? []).map((field) => (
                  <div key={field.key} className="flex flex-col gap-1">
                    <label className="text-[10px] uppercase tracking-wide text-muted-foreground">
                      {field.label}
                    </label>
                    {field.kind === "choice" ? (
                      <Select
                        value={String(triggerValues[field.key] ?? "")}
                        onValueChange={(v) => setTriggerValues((prev) => ({ ...prev, [field.key]: v }))}
                      >
                        <SelectTrigger className={cn(FIELD, "w-[150px]")}>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {(field.choices ?? []).map((choice) => (
                            <SelectItem key={choice.value} value={choice.value}>
                              {choice.label}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    ) : (
                      <Input
                        type="number"
                        inputMode="decimal"
                        step={field.step}
                        min={field.min}
                        max={field.max}
                        value={String(triggerValues[field.key] ?? "")}
                        onChange={(e) =>
                          setTriggerValues((prev) => ({ ...prev, [field.key]: Number(e.target.value) }))
                        }
                        className={cn(FIELD, "w-[90px]")}
                      />
                    )}
                  </div>
                ))}
              </>
            )}
   ```

9. In the rule-type select, after the liquidity item:
   ```tsx
                   <SelectItem value="signal">Signal</SelectItem>
   ```

- [ ] **Step 2: Verify**

Run: `npx tsc --noEmit -p .` — only the pre-existing `tests/sw.test.ts` error; `npx vitest run` — 68 passed; `npx next build` — compiles.

- [ ] **Step 3: Commit**

```bash
git add frontend/components/analysis-panel.tsx
git commit -m "Build any trigger from the Strategy panel

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: Ship and verify

- [ ] **Step 1:** Backend and frontend suites green, `next build` clean, secret scan clean.
- [ ] **Step 2:** Push `feature/indicator-triggers-ui`, open a PR, merge to main, push GitLab.
- [ ] **Step 3: Deploy** — `sudo git pull --ff-only` on the VM if the deploy key is in place, otherwise a bundle; rebuild and restart `backend` and `backtester`; both healthy. Run the build detached (`setsid nohup … > /tmp/deploy.log`), because the SSH session drops on long builds.
- [ ] **Step 4: Verify the panel's own payload arms.** For three triggers (`ema_cross`, `bollinger_squeeze`, `vwap_cross` with the week anchor), `POST /api/rules` with exactly the params `signalParams` produces — including its computed `lookback` — and expect 201, then `POST /api/rules/{id}/test` and expect no error, then delete. This is the check that the browser's warm-up arithmetic agrees with the server's.
- [ ] **Step 5: Verify the assistant sees and offers them.** `POST /api/scene` for BTCUSDT 1h and confirm `indicators` holds `stoch`, `bollinger`, `vwap`, `volume`, `atr`, and that the serialised scene is under 5,200 bytes. Then `POST /api/chat/ask` with "do you see a MACD cross, a squeeze, or a volume spike?" and confirm the findings come back with `subscribe` drafts whose step types match what was asked about.
- [ ] **Step 6: Browser** (for the user to confirm): Strategy → Build → **Signal** lists the triggers grouped, the fields change with the trigger, and Arm creates a rule that appears in Armed.
