"""
Level two of the chart fellow: turn something it sees into an alert.

The fellow says "yes, there's a sweep of support on the latest bar". Subscribing
means "tell me the next time that happens here". The rule for that is built
here, deterministically, from the scene entry the finding points at - never
from anything the model wrote. The model chose what to talk about; the
detectors decide what the alert watches for, and RuleCreate decides whether it
is a rule at all.

A finding points at a scene entry through its marks (a polyline through a W's
pivots, a bar mark on a doji's candle, a line at a sweep's level). When the
model did not mark, its label is matched against entries of the same kind that
are actually in the scene - a label alone never conjures a rule for something
the detectors did not find.

What the rule watches is the *kind* of thing, not this instance: a pattern rule
fires on any double bottom that confirms, a liquidity rule on any level of that
strength. The summary says so, so nobody arms "this W" and gets another one.
"""
import re
from typing import Any, Dict, List, Optional, Sequence

from pydantic import ValidationError

from agents.chart_fellow import PRICE_TOLERANCE
from agents.rule_parser import KIND_NAMES
from analysis.sequence import describe_steps
from models.fellow_schemas import (
    BarMark,
    FellowAnswer,
    Finding,
    HLine,
    PatternSettings,
    Polyline,
    Subscription,
)
from models.rule_schemas import RuleCreate, step_warmup


def _near(a: float, b: float) -> bool:
    return abs(a - b) <= abs(b) * PRICE_TOLERANCE


def _bar_times(finding: Finding) -> List[int]:
    return [m.time for m in finding.marks if isinstance(m, BarMark)]


def _line_prices(finding: Finding) -> List[float]:
    return [m.price for m in finding.marks if isinstance(m, HLine)]


def _norm(text: str) -> str:
    return re.sub(r"[_\-]+", " ", text.lower())


# --- resolving a finding to a scene entry ------------------------------------


def _pattern_kind_from_label(label: str) -> Optional[str]:
    text = _norm(label)
    if re.search(r"\bihs\b|invers\w* h|inverted h", text):
        return "IHS"
    if re.search(r"\bhs\b|h ?& ?s|head and shoulders|head & shoulders", text):
        return "HS"
    if "cup" in text:
        return "CUP"
    if "double bottom" in text or re.search(r"\bw\b", text):
        return "W"
    if "double top" in text or re.search(r"\bm\b", text):
        return "M"
    return None


def _pattern(finding: Finding, scene: Dict[str, Any]) -> Optional[str]:
    patterns = scene.get("patterns") or []
    for p in patterns:
        pivots = {(int(pt["t"]), float(pt["price"])) for pt in p.get("points", {}).values()}
        for mark in finding.marks:
            if isinstance(mark, Polyline) and all(
                any(t == pt.time and _near(pt.price, price) for t, price in pivots)
                for pt in mark.points
            ):
                return p["kind"]
        if any(_near(price, float(p["neckline"])) for price in _line_prices(finding)):
            return p["kind"]
    kind = _pattern_kind_from_label(finding.label)
    if kind and any(p["kind"] == kind for p in patterns):
        return kind
    return None


def _candle_shape(finding: Finding, scene: Dict[str, Any]) -> Optional[str]:
    shapes = (scene.get("candles") or {}).get("shapes") or []
    label = _norm(finding.label)
    times = set(_bar_times(finding))
    on_marks = [s["shape"] for s in shapes if int(s["t"]) in times]
    # Two shapes can share a bar (a doji that is also an inside bar); the label
    # says which one was meant.
    named = [s for s in on_marks if _norm(s) in label]
    if named:
        return named[0]
    if on_marks:
        return on_marks[0]
    for s in shapes:
        if _norm(s["shape"]) in label:
            return s["shape"]
    return None


def _structure_event(finding: Finding, scene: Dict[str, Any]) -> Optional[Dict[str, str]]:
    st = scene.get("structure") or {}
    events = list(st.get("events") or [])
    pb = st.get("pullback")
    label = _norm(finding.label)
    times = set(_bar_times(finding))
    prices = _line_prices(finding)

    def wanted(event: str) -> bool:
        # A mark on the bar is enough, unless the label names a different event.
        named = [e for e in ("sweep", "breakout", "rejection", "pullback") if e in label]
        return not named or event in named

    for e in events:
        on_bar = int(e["t"]) in times
        on_level = any(_near(p, float(e["level"])) for p in prices)
        if (on_bar or on_level) and wanted(e["event"]):
            return {"event": e["event"], "side": e["side"]}
    if pb:
        holds = pb["holds"]
        if (int(holds["t"]) in times or any(_near(p, float(holds["price"])) for p in prices)) and wanted("pullback"):
            return {"event": "pullback", "side": pb["side"]}

    # Unmarked: name the event, and the scene must have one.
    for e in events:
        if e["event"] in label or ("liquidity" in label and e["event"] == "sweep"):
            return {"event": e["event"], "side": e["side"]}
    if pb and "pullback" in label:
        return {"event": "pullback", "side": pb["side"]}
    return None


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


def _level(finding: Finding, scene: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    levels = scene.get("levels") or {}
    prices = _line_prices(finding)
    for side in ("support", "resistance"):
        for level in levels.get(side, []):
            if any(_near(p, float(level["price"])) for p in prices):
                return {"side": side, **level}
    label = _norm(finding.label)
    for side in ("support", "resistance"):
        if side in label and levels.get(side):
            return {"side": side, **levels[side][0]}
    return None


# --- building the rule -------------------------------------------------------


def _sequence(steps: List[Dict[str, Any]]) -> Dict[str, Any]:
    # A squeeze needs its whole window plus the Bollinger period; the schema
    # refuses a lookback that cannot cover the step, so compute it here.
    needed = max(step_warmup(s) for s in steps) + 3 * len(steps) + 2
    return {"agent": "sequence", "steps": steps, "lookback": max(300, needed)}


def _draft(finding: Finding, scene: Dict[str, Any], settings: PatternSettings) -> Optional[Dict[str, Any]]:
    """The rule a finding subscribes to, as RuleCreate input, plus a summary."""
    symbol = scene.get("symbol")
    timeframe = scene.get("timeframe")
    where = f"{symbol} {timeframe}"

    if finding.kind == "pattern":
        kind = _pattern(finding, scene)
        if not kind:
            return None
        noun = KIND_NAMES.get(kind, kind)
        return {
            "name": f"{symbol} {noun} confirmed",
            "params": {
                "agent": "pattern",
                "kinds": [kind],
                "states": ["confirmed"],
                "strictness": settings.strictness,
                "source": settings.source,
                "scale": settings.scale,
            },
            "summary": f"Alert when a {noun} confirms on {where} (any new one, not just this one)",
        }

    if finding.kind == "candle":
        shape = _candle_shape(finding, scene)
        if not shape:
            return None
        step = {"type": "candle", "shape": shape}
        return {
            "name": f"{symbol} {describe_steps([step])}",
            "params": _sequence([step]),
            "summary": f"Alert when a {_norm(shape)} candle closes on {where}",
        }

    if finding.kind == "structure":
        event = _structure_event(finding, scene)
        if not event:
            return None
        step = {"type": "structure", **event}
        what = f"{event['side']} {'liquidity sweep' if event['event'] == 'sweep' else event['event']}"
        return {
            "name": f"{symbol} {describe_steps([step])}",
            "params": _sequence([step]),
            "summary": f"Alert on the next {what} on {where}",
        }

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

    if finding.kind == "level":
        level = _level(finding, scene)
        if not level:
            return None
        strength = level.get("strength", "medium")
        return {
            "name": f"{symbol} near {strength} {level['side']}",
            "params": {
                "agent": "liquidity",
                "side": level["side"],
                "min_strength": strength,
                "event": "approach",
            },
            # Weak is the floor, so a weak threshold is every level.
            "summary": (
                f"Alert when price comes near any {level['side']} on {where}"
                if strength == "weak"
                else f"Alert when price comes near a {strength} or stronger {level['side']} on {where}"
            ),
        }

    return None


def subscription_for(
    finding: Finding,
    scene: Dict[str, Any],
    settings: Optional[PatternSettings] = None,
) -> Optional[Subscription]:
    """
    The alert a finding can be subscribed to, or None.

    None for anything absent, anything the guard had to correct, anything the
    rules engine cannot watch (EMA and MACD crosses, the trend read), and any
    draft the rule schema rejects.
    """
    if not finding.present or not finding.grounded:
        return None
    if not scene.get("symbol") or not scene.get("timeframe"):
        return None

    built = _draft(finding, scene, settings or PatternSettings())
    if not built:
        return None
    try:
        rule = RuleCreate(
            name=built["name"][:80],
            symbol=scene["symbol"],
            timeframe=scene["timeframe"],
            params=built["params"],
        )
    except (ValidationError, ValueError):
        return None

    return Subscription(
        summary=built["summary"],
        draft={
            "name": rule.name,
            "symbol": rule.symbol,
            "timeframe": rule.timeframe,
            "params": rule.params.model_dump(),
            "cooldown_secs": rule.cooldown_secs,
            "persist_bars": rule.resolved_persist_bars(),
        },
    )


def attach_subscriptions(
    answer: FellowAnswer,
    scene: Dict[str, Any],
    settings: Optional[PatternSettings] = None,
) -> FellowAnswer:
    """Give every finding the alert it can be subscribed to, replacing whatever was there."""
    for finding in answer.findings:
        finding.subscribe = subscription_for(finding, scene, settings)
    return answer
