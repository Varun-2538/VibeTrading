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
