"""
Which token a market is, on chain.

Duplicated from contracts/src/Addresses.sol, which is the authority - and pinned to it
by a test that parses that file, because an address that drifts here is a transaction
sent to the wrong token. The alternative, reading the list off the factory, cannot
tell which entry is which without a symbol lookup, and would still need these names.
"""
from typing import Dict, Optional

MARKET_ASSETS: Dict[str, str] = {
    "WETH/USDC": "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",
    "WBTC/USDC": "0x2f2a2543B76A4166549F7aaB2e75Bef0aefC5B0f",
}

USDC = "0xaf88d065e77c8cC2239327C5EDb3A432268e5831"


def asset_for(market: str) -> Optional[str]:
    return MARKET_ASSETS.get(market)
