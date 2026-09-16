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
