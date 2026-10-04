"""
May this rule trade? Answered from a backtest, before anything is armed.

Pure and synchronous: the caller loads the job, this decides. Two kinds of check,
and both have to pass.

*Identity* - is this report about this rule at all? A gate that accepted any
report the owner happened to have would be theatre, so the params, the exit plan,
the direction settings, the timeframe and the parity version all have to match
what is being armed.

*Quality* - did it work on data the tuner never saw? Only the unseen half counts.
The seen half is selected by construction and flatters itself; the report already
separates them and flags a collapse between them, and those flags are honoured
here rather than re-derived.

Every failure is reported, not the first. An owner fixing one at a time learns
nothing about the others, and this is the only place that will ever tell them why
their strategy is not allowed to spend.
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from models.execution_schemas import (
    MAX_POSITION_AGE_MS,
    DexTradeActionConfig,
    PreflightThresholds,
)
from services.execution.markets import base_of, trades_symbol
from services.history_service import TIMEFRAME_MS
from services.trade_plan import BEHAVIOURAL_FIELDS, PARITY_VERSION

# Evidence older than this is not evidence. Two weeks is roughly when a regime
# has had time to change without anyone noticing it did.
MAX_EVIDENCE_AGE_DAYS = 14

# Once an account has traded this many positions, its own measured costs are used
# to check the report's assumptions. Below it there is nothing to compare.
MIN_POSITIONS_FOR_COST_CHECK = 10
COST_TOLERANCE = 1.5


@dataclass(frozen=True)
class PreflightResult:
    passed: bool
    reasons: List[str] = field(default_factory=list)
    evidence: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {"passed": self.passed, "reasons": list(self.reasons), "evidence": dict(self.evidence)}


def _behavioural(plan: Dict[str, Any]) -> Dict[str, Any]:
    return {k: plan.get(k) for k in BEHAVIOURAL_FIELDS}


def check(
    rule: Dict[str, Any],
    action: DexTradeActionConfig,
    job: Optional[Dict[str, Any]],
    *,
    thresholds: PreflightThresholds,
    now: datetime,
    realised_cost_r: Optional[float] = None,
    positions_closed: int = 0,
) -> PreflightResult:
    reasons: List[str] = []

    if job is None:
        return PreflightResult(False, ["No backtest with that id belongs to this wallet."])
    if job.get("status") != "done":
        return PreflightResult(
            False, [f"That backtest is {job.get('status')}, not done. Arm it once it has finished."]
        )
    report = job.get("report") or {}
    meta = report.get("meta") or {}
    trades = (report.get("trades") or {}).get("unseen") or {}
    study = (report.get("study") or {}).get("unseen") or {}
    if not meta or not trades:
        return PreflightResult(False, ["That backtest has no report to read."])

    # --- identity: the report has to be about this rule, armed this way.
    if str(job.get("rule_id") or "") != str(rule["id"]):
        reasons.append("That backtest was not run for this rule.")
    if (meta.get("symbol") or "").upper() != (rule["symbol"] or "").upper():
        reasons.append(f"The backtest is on {meta.get('symbol')}, the rule is on {rule['symbol']}.")
    if not trades_symbol(action.market, rule["symbol"]):
        reasons.append(
            f"This rule watches {rule['symbol']}, and {action.market} holds {base_of(action.market)}. "
            "A rule can only trade the coin it watches."
        )
    if meta.get("timeframe") != rule["timeframe"]:
        reasons.append(f"The backtest is on {meta.get('timeframe')}, the rule is on {rule['timeframe']}.")
    if (meta.get("params") or {}) != (rule["params"] or {}):
        reasons.append("The rule's settings have changed since that backtest. Run it again.")

    armed = _behavioural(action.exit.model_dump())
    measured = _behavioural(meta.get("exit") or {})
    if armed != measured:
        differs = sorted(k for k in armed if armed[k] != measured.get(k))
        reasons.append("The exit plan differs from the one measured: " + ", ".join(differs) + ".")

    if meta.get("neutral") != action.neutral:
        reasons.append(
            f"The backtest read directionless signals as '{meta.get('neutral')}', "
            f"this arms them as '{action.neutral}'."
        )
    if meta.get("sides") != action.sides:
        reasons.append(
            "A pool cannot short, so this needs a long-only backtest; that one measured "
            f"'{meta.get('sides') or 'both'}'."
        )
    if meta.get("parity_version") != PARITY_VERSION:
        reasons.append(
            "That backtest was measured under different exit arithmetic "
            f"(v{meta.get('parity_version')}, now v{PARITY_VERSION}). Run it again."
        )

    to_ms = meta.get("to")
    if to_ms:
        measured_at = datetime.fromtimestamp(int(to_ms) / 1000, tz=timezone.utc)
        if now - measured_at > timedelta(days=MAX_EVIDENCE_AGE_DAYS):
            reasons.append(
                f"That backtest ends {(now - measured_at).days} days ago; evidence has to be "
                f"newer than {MAX_EVIDENCE_AGE_DAYS} days."
            )

    # A bar limit that is reasonable to ask of history is not always reasonable to
    # hold a real position through.
    step = TIMEFRAME_MS.get(rule["timeframe"])
    if step and action.exit.max_bars * step > MAX_POSITION_AGE_MS:
        days = MAX_POSITION_AGE_MS // (24 * 60 * 60 * 1000)
        reasons.append(
            f"{action.exit.max_bars} bars of {rule['timeframe']} is longer than {days} days; "
            "shorten max_bars."
        )

    # --- quality: only the unseen half, and only what the report already says.
    count = int(trades.get("trades") or 0)
    if count < thresholds.min_trades:
        reasons.append(f"{count} unseen trades; {thresholds.min_trades} is the least that says anything.")

    expectancy = trades.get("expectancy_r")
    if expectancy is None:
        reasons.append("The unseen half has no expectancy to read.")
    elif expectancy < thresholds.min_expectancy_r:
        reasons.append(
            f"Unseen expectancy {expectancy:+.3f}R is below your {thresholds.min_expectancy_r:+.3f}R."
        )

    drawdown = trades.get("max_drawdown_pct")
    if drawdown is not None and -drawdown > thresholds.max_drawdown_pct:
        reasons.append(
            f"Unseen drawdown {drawdown:.1f}% is worse than your {-thresholds.max_drawdown_pct:.1f}%."
        )

    if "likely_overfit" in (report.get("flags") or []):
        reasons.append("The unseen half collapsed against the seen half, so the settings fit noise.")
    if "too_few_trades" in (trades.get("flags") or []):
        reasons.append("The report itself flags too few unseen trades.")
    if "no_edge_detected" in (study.get("flags") or []):
        reasons.append("The signal showed no edge on unseen data, whatever the trades did.")

    # --- cost honesty: a strategy measured at one cost is not the same strategy
    # at another. Only asked once this account has fills of its own to compare.
    modelled_cost = trades.get("cost_r")
    if (
        positions_closed >= MIN_POSITIONS_FOR_COST_CHECK
        and realised_cost_r is not None
        and modelled_cost is not None
        and realised_cost_r > modelled_cost * COST_TOLERANCE
    ):
        reasons.append(
            f"This account really pays {realised_cost_r:.3f}R a trade; the report assumed "
            f"{modelled_cost:.3f}R. Re-measure with your costs."
        )

    return PreflightResult(
        passed=not reasons,
        reasons=reasons,
        evidence={
            "backtest_job_id": str(job.get("id")),
            "measured_to": to_ms,
            "unseen_trades": count,
            "unseen_expectancy_r": expectancy,
            "unseen_max_drawdown_pct": drawdown,
            "unseen_cost_r": modelled_cost,
            "gross_expectancy_r": trades.get("gross_expectancy_r"),
            "sides": meta.get("sides"),
            "parity_version": meta.get("parity_version"),
            "tuned": "tuned" in (report.get("flags") or []),
            "thresholds": thresholds.model_dump(),
        },
    )
