"""
Which venue an intent trades on.

Shadow and live are the same code path with a different venue behind it, which is the
point: there is no live-only branch that shadow has never exercised.

Live needs three things to exist - a signing key, a factory address, and a vault the
owner actually deployed - and the absence of any of them is a **refusal**, never a
quiet downgrade to shadow. Pretending to trade is worse than admitting we cannot, and
an account that believed it was live while nothing was sent would find out from its
equity curve rather than from us.
"""
from typing import Any, Dict, Optional

from services.execution.chain import Chain
from services.execution.markets import asset_for
from services.execution.shadow import ShadowVenue
from services.execution.signer import Signer, signer_from_settings
from services.execution.vault_venue import VaultVenue
from services.execution.venue import Venue, VenueRejected

KNOWN_VENUES = ("uniswap_v3_arbitrum",)

_chain: Optional[Chain] = None
_signer: Optional[Signer] = None
_signer_loaded = False


class NoAdapter(VenueRejected):
    """Live mode was asked for with something it needs still missing."""


def chain() -> Chain:
    """One client for the process: a fresh TLS handshake per call is not free."""
    global _chain
    if _chain is None:
        from config import settings

        _chain = Chain(settings.arbitrum_rpc_url, settings.arbitrum_chain_id)
    return _chain


def signer() -> Optional[Signer]:
    """
    The executor's signer, or None.

    None is a normal state: shadow needs no key, and an executor without one should
    idle rather than refuse to start.
    """
    global _signer, _signer_loaded
    if not _signer_loaded:
        _signer = signer_from_settings()
        _signer_loaded = True
    return _signer


async def close_chain() -> None:
    global _chain
    if _chain is not None:
        await _chain.close()
        _chain = None


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
        from config import settings

        key = signer()
        if key is None:
            raise NoAdapter("live execution needs a signing key; none is configured")
        if not settings.vault_factory_address:
            raise NoAdapter("live execution needs the vault factory address")
        market = source.get("market") or (position or {}).get("market") or ""
        asset = asset_for(market)
        if asset is None:
            raise NoAdapter(f"no on-chain asset for market {market!r}")
        return VaultVenue(
            chain=chain(),
            signer=key,
            market=market,
            owner=(account or {}).get("owner_key"),
            asset=asset,
            factory=settings.vault_factory_address,
            eth_usd_feed=settings.eth_usd_feed or None,
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
