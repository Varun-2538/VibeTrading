"""
What a rule's `action` may be, and what an account may allow.

A discriminated union on `kind`, for the same reason rule_schemas.py uses one on
`agent`: a misspelled field has to be a 422 when it is written, not a rule that is
accepted and then behaves in a way nobody asked for. The stakes are higher here.
A loose dict there produced a rule that silently never fired; a loose dict here
produces a rule that spends money on terms nobody validated.

ExitPlan is imported and nested verbatim - not copied, not subsetted. There is one
type for how a signal becomes a trade, and the backtester and the executor both
read it, so they cannot drift.
"""
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, Field, model_validator

from models.backtest_schemas import ExitPlan
from services.execution.markets import BY_MARKET
from services.trade_plan import PARITY_VERSION

# Venues an action may name, one per chain. The string is stored on the policy row
# so a rule records which chain it was armed for and a later one cannot be read as it.
Venue = Literal["uniswap_v3_arbitrum", "uniswap_v3_robinhood"]
VENUES = ("uniswap_v3_arbitrum", "uniswap_v3_robinhood")

# Markets, as the vault understands them: the asset a position is held in, against
# the stablecoin it returns to. The quote token names the chain - USDC is Arbitrum
# One's, USDG is Robinhood Chain's - so no market is on two chains.
Market = Literal["WETH/USDC", "WBTC/USDC", "WETH/USDG"]
MARKETS = ("WETH/USDC", "WBTC/USDC", "WETH/USDG")

# The longest a live position may stay open, whatever max_bars says. ExitPlan
# allows max_bars up to 500, which on a daily chart is sixteen months - fine as a
# backtest question, not something to hold a real position through.
MAX_POSITION_AGE_MS = 45 * 24 * 60 * 60 * 1000  # 45 days


class AlertActionConfig(BaseModel):
    """The only action that exists today: tell the owner, spend nothing."""

    kind: Literal["alert"] = "alert"


class DexTradeActionConfig(BaseModel):
    """
    Trade the fire on a decentralised exchange, inside the owner's own vault.

    Every behavioural field here is also a field the backtest measured, and the
    arming gate compares them one by one. What is *not* here is anything about
    keys, addresses or approvals: this is a description of a strategy, and the
    permission to act on it lives on-chain where the owner can revoke it.
    """

    kind: Literal["dex_trade"] = "dex_trade"
    # Optional because the market already decides it; when sent, it must agree.
    venue: Optional[Venue] = None
    market: Market

    # Verbatim, so live and the report cannot mean different things by a stop.
    exit: ExitPlan

    # These two live on BacktestCreate rather than on ExitPlan, because they decide
    # whether a trade happens rather than how it ends - and they have to be here
    # too, or a live fire with no direction of its own has no defined behaviour.
    neutral: Literal["skip", "long", "short"] = "skip"
    # A spot pool cannot short. Fixed rather than chosen: an action that claimed
    # otherwise would be armed against evidence the venue cannot produce.
    sides: Literal["long"] = "long"

    # backtest/trades.py enters at the next bar's open. Live cannot be exact, so
    # this is how much later than that open a fill is still the same trade.
    max_entry_delay_secs: int = Field(default=120, ge=10, le=3600)
    # What the swap's minimum-out is set from. Wider on the way out, in the
    # executor: a stop that cannot fill because of a slippage guard is not a stop.
    max_slippage_bps: int = Field(default=50, ge=1, le=1000)
    # A per-rule ceiling. The account's ceiling wins wherever it is lower.
    max_notional_usd: float = Field(default=100, gt=0, le=1_000_000)

    @model_validator(mode="after")
    def _must_have_a_way_out(self) -> "DexTradeActionConfig":
        """
        A live position needs a bound that is not the stop. The stop may never be
        reached; without a target or a believable bar limit the position is simply
        held, which is not a strategy anyone backtested.
        """
        no_target = self.exit.target_r is None and self.exit.target_pct is None
        if no_target and self.exit.max_bars > 200:
            raise ValueError(
                "A live trade needs a way out: set a target, or bring max_bars "
                "under 200 so the time exit is a real bound"
            )
        return self

    @model_validator(mode="after")
    def _venue_follows_market(self) -> "DexTradeActionConfig":
        """
        The market decides the chain. A venue that disagrees is a 422, not a
        tiebreak: either reading would arm a rule on a chain the owner did not pick.
        """
        venue = BY_MARKET[self.market].venue
        if self.venue is None:
            self.venue = venue
        elif self.venue != venue:
            raise ValueError(f"{self.market} trades on {venue}, not {self.venue}")
        return self


RuleAction = Annotated[
    Union[AlertActionConfig, DexTradeActionConfig],
    Field(discriminator="kind"),
]


class PreflightThresholds(BaseModel):
    """
    The bar a strategy has to clear on unseen data before it may trade.

    The owner sets these - it is their money and their patience - but not the
    floor: an expectancy of zero or less cannot be armed whatever anyone wants,
    because there is no reading of a losing unseen result that makes it evidence.
    """

    min_expectancy_r: float = Field(default=0.10, gt=0, le=10)
    max_drawdown_pct: float = Field(default=25.0, gt=0, le=90)
    # Not settable. Thirty trades is where the report stops calling itself
    # too_few_trades, and a preference cannot make a small sample larger.
    min_trades: int = Field(default=30, ge=30, le=30)


class ArmRequest(BaseModel):
    """
    Arm a rule for execution, naming the evidence.

    The backtest is named rather than searched for, so the gate reports on the
    report the owner meant and never silently picks a kinder one.
    """

    action: DexTradeActionConfig
    backtest_job_id: str = Field(min_length=1)
    thresholds: PreflightThresholds = Field(default_factory=PreflightThresholds)


class AccountSettings(BaseModel):
    """
    Per-wallet rails. Every field is a ceiling; none of them is a target.

    They live at account level rather than on a rule because they bound aggregate
    exposure: a per-rule daily loss limit is worthless, since ten rules each
    losing nine tenths of their own limit is a blown account.
    """

    mode: Literal["off", "shadow", "live"] = "off"
    equity_usd: float = Field(default=0, ge=0, le=10_000_000)
    max_notional_usd: float = Field(default=100, gt=0, le=1_000_000)
    max_concurrent_positions: int = Field(default=1, ge=0, le=20)
    max_trades_per_day: int = Field(default=5, ge=0, le=200)
    daily_loss_limit_usd: float = Field(default=25, gt=0, le=1_000_000)

    @model_validator(mode="after")
    def _live_needs_something_to_trade_with(self) -> "AccountSettings":
        if self.mode == "live" and self.equity_usd <= 0:
            raise ValueError("Live mode needs the vault's size: set equity_usd")
        return self


class ArmedPolicy(BaseModel):
    """What the server agreed to, as the API reports it back."""

    rule_id: str
    armed: bool
    venue: str
    market: str
    parity_version: int
    backtest_job_id: Optional[str] = None
    armed_at: Optional[str] = None
    disarmed_reason: Optional[str] = None
    exit: Optional[ExitPlan] = None
    preflight: Optional[dict] = None

    @staticmethod
    def parity_is_current(parity_version: int) -> bool:
        return parity_version == PARITY_VERSION
