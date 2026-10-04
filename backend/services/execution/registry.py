"""
Which venue an intent trades on.

One dict, hand-maintained, for the same reason `services/actions/__init__.py` is one
dict: auditability matters more than extensibility once an entry can spend money.

Today there is one entry and it spends nothing. `uniswap_v3_arbitrum` is *registered*
so a policy can be armed for it and so the shape is exercised, but it resolves to the
shadow wrapper until the vault adapter lands. An account in live mode with no adapter
gets a refusal rather than a silent downgrade to shadow - pretending to trade is
worse than admitting we cannot.
"""
from typing import Any, Dict, Optional

from services.execution.shadow import ShadowVenue
from services.execution.venue import Venue, VenueRejected

KNOWN_VENUES = ("uniswap_v3_arbitrum",)


class NoAdapter(VenueRejected):
    """Live mode was asked for on a venue we cannot yet reach."""


def venue_for(
    intent: Optional[Dict[str, Any]],
    account: Optional[Dict[str, Any]],
    position: Optional[Dict[str, Any]],
    *,
    candles=None,
) -> Venue:
    """
    The venue for a piece of work, from whichever of the three rows is present.

    An intent, a position, or neither: the monitor has a position and no intent, the
    runner has an intent and maybe a position, and reconciliation may have only the
    order. All three need the same venue, so the lookup takes what it can get.
    """
    source = intent or position or {}
    mode = (source.get("mode") or (account or {}).get("mode") or "off")
    name = source.get("venue") or (KNOWN_VENUES[0] if KNOWN_VENUES else "")
    if name not in KNOWN_VENUES:
        raise VenueRejected(f"unknown venue {name!r}")

    reference = (source.get("reference") or {}) if intent else {}
    symbol = reference.get("symbol") or (position or {}).get("symbol")
    timeframe = reference.get("timeframe") or (position or {}).get("timeframe")
    plan = source.get("plan") or {}

    if mode == "live":
        raise NoAdapter(
            "live execution has no venue adapter yet; the vault adapter lands with the "
            "next slice"
        )

    kwargs: Dict[str, Any] = {
        "symbol": symbol,
        "timeframe": timeframe,
        "plan": plan,
        "equity_usd": float((account or {}).get("equity_usd") or 0),
        "position_row": position,
    }
    if candles is not None:
        kwargs["candles"] = candles
    return ShadowVenue(**kwargs)
