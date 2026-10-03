"""
What a backtest request may be.

The rule is a RuleCreate - the same schema that arms a rule - so anything the
Strategy panel or the chat can draft can be backtested, and nothing else can.
"""
from typing import List, Literal, Optional, Tuple

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


class ExitPlan(BaseModel):
    """
    How a signal becomes a trade and how the trade ends. The defaults are a
    starting point for the report, not advice.
    """

    stop_atr: Optional[float] = Field(default=1.5, gt=0, le=20)
    stop_pct: Optional[float] = Field(default=None, gt=0, le=50)
    target_r: Optional[float] = Field(default=2.0, gt=0, le=20)
    target_pct: Optional[float] = Field(default=None, gt=0, le=200)
    max_bars: int = Field(default=20, ge=1, le=500)
    exit_on_opposite: bool = False
    fee_pct: float = Field(default=0.1, ge=0, le=1)
    slippage_pct: float = Field(default=0.02, ge=0, le=1)
    risk_pct: float = Field(default=1.0, gt=0, le=10)

    @model_validator(mode="after")
    def _has_a_stop(self) -> "ExitPlan":
        if self.stop_atr is None and self.stop_pct is None:
            raise ValueError("An exit plan needs a stop: stop_atr or stop_pct")
        return self



# The most settings one job may search. Each one is cheap against a cached
# tape, but the report has to stay readable and the queue has to keep moving.
MAX_COMBINATIONS = 200


class Grid(BaseModel):
    """
    What tuning is allowed to vary. The rule's own filter is varied too, by
    agent: confidence for patterns, level strength for liquidity, nothing for
    sequences - a sequence step is either matched or it is not.
    """

    stop_atr: List[float] = Field(default=[1.0, 1.5, 2.0], min_length=1, max_length=10)
    target_r: List[float] = Field(default=[1.0, 2.0, 3.0], min_length=1, max_length=10)
    max_bars: List[int] = Field(default=[10, 20, 40], min_length=1, max_length=10)
    min_confidence: List[float] = Field(default=[60.0, 70.0, 80.0], min_length=1, max_length=10)
    min_strength: List[Literal["weak", "medium", "strong"]] = Field(
        default=["weak", "medium", "strong"], min_length=1, max_length=10
    )


def grid_size(grid: Grid, agent: str) -> int:
    filters = {"pattern": len(grid.min_confidence), "liquidity": len(grid.min_strength)}.get(agent, 1)
    return len(grid.stop_atr) * len(grid.target_r) * len(grid.max_bars) * filters


class BacktestCreate(BaseModel):
    rule: RuleCreate
    # Signals with no direction of their own (doji, inside bar): skipped, or
    # read as long or short.
    neutral: Literal["skip", "long", "short"] = "skip"
    # Fraction of evaluated bars that are "seen"; the rest are unseen.
    split: float = Field(default=0.7, ge=0.5, le=0.9)
    exit: ExitPlan = Field(default_factory=ExitPlan)
    # Search the grid on seen data and verify the winner once on unseen data.
    tune: bool = False
    grid: Grid = Field(default_factory=Grid)

    @model_validator(mode="after")
    def _timeframe_has_history(self) -> "BacktestCreate":
        if self.rule.timeframe not in BACKTEST_TIMEFRAMES:
            raise ValueError("Backtests run on 5m, 15m, 1h or 1d")
        if self.tune:
            size = grid_size(self.grid, self.rule.params.agent)
            if size > MAX_COMBINATIONS:
                raise ValueError(
                    f"That grid is {size} combinations; at most {MAX_COMBINATIONS} can be searched"
                )
        return self
