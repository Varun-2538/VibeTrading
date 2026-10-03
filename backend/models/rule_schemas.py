"""
Request and response shapes for strategy rules.

Rule parameters are validated as a discriminated union on `agent` so a
misspelled field is rejected at create time. The alternative - a loose dict -
produces a rule that is accepted and then silently never fires, which is the
worst possible failure for an alert you are relying on.
"""
from datetime import datetime
from typing import Annotated, Any, Dict, List, Literal, Optional, Union
from uuid import UUID

from pydantic import BaseModel, Field

from analysis.candles import DEFAULT_DOJI_BODY_PCT
from analysis.levels import MAX_LEVELS_PER_SIDE  # noqa: F401  (kept for callers)
from analysis.patterns import DEFAULT_SCALE, KINDS, PRESETS, SCALES, SOURCES
from analysis.sequence import DEFAULT_WITHIN_BARS

# Ordered weakest to strongest, so "at least medium" is a slice of this list.
STRENGTH_ORDER = ("weak", "medium", "strong")
PATTERN_STATES = ("forming", "approaching", "confirmed")

PatternKind = Literal["W", "M"]
PatternState = Literal["forming", "approaching", "confirmed"]
Strength = Literal["weak", "medium", "strong"]


class PatternRuleParams(BaseModel):
    """Fires on a double bottom/top matching the filters below."""

    agent: Literal["pattern"] = "pattern"
    kinds: List[PatternKind] = Field(default_factory=lambda: list(KINDS), min_length=1)
    # Only `confirmed` is safe to act on. The other two are visible to alerts
    # but are marked provisional, because both are judged against the newest
    # close and one opposing bar undoes them.
    states: List[PatternState] = Field(default_factory=lambda: ["confirmed"], min_length=1)
    min_confidence: float = Field(default=70.0, ge=0, le=100)
    strictness: str = "balanced"
    source: str = "wick"
    scale: str = DEFAULT_SCALE
    lookback: int = Field(default=500, ge=50, le=1000)

    def model_post_init(self, _context: Any) -> None:
        if self.strictness not in PRESETS:
            raise ValueError(
                f"Unknown strictness '{self.strictness}'. "
                f"Expected one of: {', '.join(PRESETS)}"
            )
        if self.source not in SOURCES:
            raise ValueError(
                f"Unknown source '{self.source}'. Expected one of: {', '.join(SOURCES)}"
            )
        if self.scale not in SCALES:
            raise ValueError(
                f"Unknown scale '{self.scale}'. Expected one of: {', '.join(SCALES)}"
            )


class LiquidityRuleParams(BaseModel):
    """Fires when price approaches or breaks a support/resistance level."""

    agent: Literal["liquidity"] = "liquidity"
    side: Literal["support", "resistance"] = "support"
    min_strength: Strength = "medium"
    # `approach` fires while price sits within proximity_pct of the level;
    # `break` fires on the close that crosses it.
    event: Literal["approach", "break"] = "approach"
    proximity_pct: float = Field(default=0.3, gt=0, le=50)
    lookback: int = Field(default=500, ge=50, le=1000)


class CandleStep(BaseModel):
    """One bar has a shape. Settled at close; cannot repaint."""

    type: Literal["candle"] = "candle"
    shape: Literal["doji"] = "doji"
    # Body as a percentage of the bar's high-low range.
    max_body_pct: float = Field(default=DEFAULT_DOJI_BODY_PCT, gt=0, le=50)


class IndicatorStep(BaseModel):
    """An indicator crosses a level on a bar."""

    type: Literal["indicator"] = "indicator"
    indicator: Literal["rsi"] = "rsi"
    period: int = Field(default=14, ge=2, le=200)
    cross: Literal["above", "below"] = "above"
    level: float = Field(default=30.0, ge=0, le=100)


SequenceStep = Union[CandleStep, IndicatorStep]


class SequenceRuleParams(BaseModel):
    """
    Fires when the steps occur in order, the last one on the newest closed bar.

    "Doji, then RSI(14) crosses above 30, within 3 bars" is two steps and a
    window. Because every step is settled at candle close, sequence rules do
    not need the persistence wait that pattern rules do - see RuleCreate.
    """

    agent: Literal["sequence"] = "sequence"
    steps: List[Annotated[SequenceStep, Field(discriminator="type")]] = Field(
        min_length=1, max_length=4
    )
    within_bars: int = Field(default=DEFAULT_WITHIN_BARS, ge=1, le=50)
    lookback: int = Field(default=300, ge=50, le=1000)

    def model_post_init(self, _context: Any) -> None:
        # Pydantic picks the step model from `type`, so a bad `type` is already
        # a 422 by here. What it cannot check is that the lookback leaves room
        # for the longest indicator warm-up plus the window.
        longest = max(
            (s.period for s in self.steps if isinstance(s, IndicatorStep)), default=0
        )
        needed = longest + self.within_bars * len(self.steps) + 2
        if self.lookback < needed:
            raise ValueError(
                f"lookback {self.lookback} is too short for these steps; "
                f"need at least {needed} bars"
            )


RuleParams = Union[PatternRuleParams, LiquidityRuleParams, SequenceRuleParams]


class RuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    symbol: str = Field(min_length=3, max_length=20)
    timeframe: str = "1h"
    params: RuleParams = Field(discriminator="agent")
    cooldown_secs: int = Field(default=900, ge=0, le=86_400)
    # None means "the right default for this agent": one extra close for
    # patterns, which can repaint, and none for sequences, which cannot.
    persist_bars: Optional[int] = Field(default=None, ge=0, le=5)

    def resolved_persist_bars(self) -> int:
        if self.persist_bars is not None:
            return self.persist_bars
        return 0 if self.params.agent == "sequence" else 1


class RuleUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=80)
    enabled: Optional[bool] = None
    params: Optional[RuleParams] = Field(default=None, discriminator="agent")
    cooldown_secs: Optional[int] = Field(default=None, ge=0, le=86_400)
    persist_bars: Optional[int] = Field(default=None, ge=0, le=5)


class RuleOut(BaseModel):
    id: UUID
    name: str
    agent: str
    symbol: str
    timeframe: str
    params: Dict[str, Any]
    action: Dict[str, Any]
    enabled: bool
    cooldown_secs: int
    persist_bars: int
    last_fired_at: Optional[datetime]
    fire_count: int
    created_at: datetime


class RuleEventOut(BaseModel):
    id: int
    rule_id: UUID
    rule_name: Optional[str] = None
    symbol: str
    timeframe: str
    agent: str
    direction: Optional[str]
    price: float
    candle_time: datetime
    fired_at: datetime
    provisional: bool
    evidence: Dict[str, Any]
    action_kind: str
    action_status: str


class RuleTestOut(BaseModel):
    would_fire: bool
    # Why a matching signal would still not fire: cooldown, persistence, dedup,
    # or no_match when nothing matched at all.
    blocked_by: Optional[str] = None
    signal: Optional[Dict[str, Any]] = None
