"""
Which chain a market is on, and which token it is there.

Duplicated from contracts/src/Addresses.sol, which is the authority - and pinned to it
by a test that parses that file, because an address that drifts here is a transaction
sent to the wrong token. The alternative, reading the list off the factory, cannot
tell which entry is which without a symbol lookup, and would still need these names.

A market's name decides its chain: the quote token is that chain's dollar, USDC on
Arbitrum One and USDG on Robinhood Chain, and no name appears on two chains. So a rule
armed for "WETH/USDG" cannot be routed to Arbitrum by a default somewhere - there is
nothing to default.
"""
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple


@dataclass(frozen=True)
class ChainInfo:
    """One chain we execute on. Settings supply the parts that are deployment-specific."""

    key: str  # "arbitrum", "robinhood" - the prefix of its settings
    chain_id: int
    name: str
    venue: str  # what a policy row records, so a later venue cannot be read as this one
    stable: str  # the token a vault is flat in
    stable_symbol: str
    eth_usd_feed: str  # Chainlink ETH/USD on this chain, used only to price gas
    markets: Dict[str, str] = field(default_factory=dict)  # market name -> asset address
    explorer: str = ""


ARBITRUM = ChainInfo(
    key="arbitrum",
    chain_id=42161,
    name="Arbitrum One",
    venue="uniswap_v3_arbitrum",
    stable="0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
    stable_symbol="USDC",
    eth_usd_feed="0x639Fe6ab55C921f74e7fac1ee960C0B6293ba612",
    markets={
        "WETH/USDC": "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",
        "WBTC/USDC": "0x2f2a2543B76A4166549F7aaB2e75Bef0aefC5B0f",
    },
    explorer="https://arbiscan.io",
)

ROBINHOOD = ChainInfo(
    key="robinhood",
    chain_id=4663,
    name="Robinhood Chain",
    venue="uniswap_v3_robinhood",
    stable="0x5fc5360D0400a0Fd4f2af552ADD042D716F1d168",
    stable_symbol="USDG",
    eth_usd_feed="0x78F3556b67E17Df817D51Ef5a990cDaF09E8d3A9",
    markets={
        "WETH/USDG": "0x0Bd7D308f8E1639FAb988df18A8011f41EAcAD73",
    },
    explorer="https://robinhoodchain.blockscout.com",
)

CHAINS: Tuple[ChainInfo, ...] = (ARBITRUM, ROBINHOOD)
BY_VENUE: Dict[str, ChainInfo] = {c.venue: c for c in CHAINS}
BY_MARKET: Dict[str, ChainInfo] = {m: c for c in CHAINS for m in c.markets}

# Every market on every chain; safe as one map because no name is on two chains.
MARKET_ASSETS: Dict[str, str] = {m: a for c in CHAINS for m, a in c.markets.items()}
USDC = ARBITRUM.stable


def base_of(market: str) -> str:
    """The coin a market holds, as the signal names it: "WETH/USDG" -> "ETH"."""
    held = market.split("/")[0].upper()
    return held[1:] if held in ("WETH", "WBTC") else held


def trades_symbol(market: str, symbol: str) -> bool:
    """
    Whether a rule watching `symbol` may trade `market`. Signals come from Binance
    pairs like ETHUSDT; the market holds the wrapped coin. A rule watching BTC that
    trades ETH would be acting on somebody else's chart.
    """
    return (symbol or "").upper().startswith(base_of(market)) and market in MARKET_ASSETS


def asset_for(market: str) -> Optional[str]:
    return MARKET_ASSETS.get(market)


def factory_address(info: ChainInfo) -> str:
    """This chain's vault factory, from settings; empty until it is deployed there."""
    from config import settings

    return getattr(settings, f"{info.key}_vault_factory_address") or ""


def chain_for_market(market: str) -> Optional[ChainInfo]:
    return BY_MARKET.get(market)


def chain_for_venue(venue: str) -> Optional[ChainInfo]:
    return BY_VENUE.get(venue)
