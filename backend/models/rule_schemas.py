"""
Request and response shapes for strategy rules.

Rule parameters are validated as a discriminated union on `agent` so a
misspelled field is rejected at create time. The alternative - a loose dict -
produces a rule that is accepted and then silently never fires, which is the
worst possible failure for an alert you are relying on.
"""
from datetime import datetime
from typing import Annotated, Any, Dict, List, Literal, Optional, Tuple, Union
from uuid import UUID

from pydantic import BaseModel, Field

from analysis.candles import DEFAULT_DOJI_BODY_PCT, SHAPES
from analysis.levels import MAX_LEVELS_PER_SIDE  # noqa: F401  (kept for callers)
from analysis.patterns import DEFAULT_SCALE, KINDS, PRESETS, SCALES, SOURCES
from analysis.patterns_big import ALL_KINDS
from analysis.sequence import DEFAULT_WITHIN_BARS
from analysis.structure import EVENTS as STRUCTURE_EVENTS
from analysis.structure import SIDES as STRUCTURE_SIDES

# Ordered weakest to strongest, so "at least medium" is a slice of this list.
STRENGTH_ORDER = ("weak", "medium", "strong")
PATTERN_STATES = ("forming", "approaching", "confirmed")

PatternKind = Literal[ALL_KINDS]  # type: ignore[valid-type]
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
    # Subscripting Literal with the tuple unpacks it, so the schema follows
    # analysis.candles.SHAPES without a second list to keep in step.
    shape: Literal[SHAPES] = "doji"  # type: ignore[valid-type]
    # Body as a percentage of the bar's high-low range.
    max_body_pct: float = Field(default=DEFAULT_DOJI_BODY_PCT, gt=0, le=50)


class IndicatorStep(BaseModel):
    """An indicator crosses a level on a bar."""

    type: Literal["indicator"] = "indicator"
    indicator: Literal["rsi"] = "rsi"
    period: int = Field(default=14, ge=2, le=200)
    cross: Literal["above", "below"] = "above"
    level: float = Field(default=30.0, ge=0, le=100)


class StructureStep(BaseModel):
    """
    Price did something at a level: swept it, broke it, or rejected off it -
    or the newest bar is a pullback inside the trend. Judged on closed bars
    against levels from the bars before, so it cannot repaint.
    """

    type: Literal["structure"] = "structure"
    event: Literal[STRUCTURE_EVENTS] = "sweep"  # type: ignore[valid-type]
    side: Literal[STRUCTURE_SIDES] = "bullish"  # type: ignore[valid-type]


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
        # for the slowest step's warm-up plus the window between steps.
        longest = max(step_warmup(s.model_dump()) for s in self.steps)
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

    def model_post_init(self, _context: Any) -> None:
        # A session VWAP over a single daily candle is that candle's own
        # typical price, so the rule could never mean what it says.
        if self.timeframe == "1d" and self.params.agent == "sequence":
            for step in self.params.steps:
                if getattr(step, "type", None) == "vwap_cross" and step.anchor == "day":
                    raise ValueError(
                        "A day-anchored VWAP means nothing on daily candles; use the week anchor"
                    )

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
