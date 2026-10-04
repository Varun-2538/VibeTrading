"""
Two chains, and the rules that keep a rule on the one it was armed for.

The market names the chain - USDC is Arbitrum One's dollar, USDG is Robinhood
Chain's - so every place that could route a trade has to agree with that, and
disagreement has to be a refusal rather than a tiebreak.
"""
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from models.execution_schemas import DexTradeActionConfig, PreflightThresholds
from services.execution import registry
from services.execution.markets import (
    ARBITRUM,
    CHAINS,
    ROBINHOOD,
    base_of,
    chain_for_market,
    trades_symbol,
)
from services.execution.shadow import ShadowVenue
from services.execution.vault_venue import VaultVenue
from services.execution.venue import VenueRejected

EXIT = {"stop_atr": 1.5, "target_r": 2.0, "max_bars": 20}


class _Key:
    address = "0x000000000000000000000000000000000000dEaD"


@pytest.fixture
def live(monkeypatch):
    """A configured executor: a key, and a factory on each chain."""
    from config import settings

    monkeypatch.setattr(registry, "_signer", _Key())
    monkeypatch.setattr(registry, "_signer_loaded", True)
    monkeypatch.setattr(registry, "_chains", {})
    monkeypatch.setattr(settings, "arbitrum_vault_factory_address", "0x" + "a" * 40)
    monkeypatch.setattr(settings, "robinhood_vault_factory_address", "0x" + "b" * 40)
    return settings


def _intent(**over):
    row = {"mode": "live", "venue": "uniswap_v3_robinhood", "market": "WETH/USDG"}
    row.update(over)
    return row


class TestTheMarketNamesTheChain:
    def test_no_market_is_on_two_chains(self):
        names = [m for c in CHAINS for m in c.markets]
        assert len(names) == len(set(names))

    def test_each_venue_is_one_chain(self):
        assert len({c.venue for c in CHAINS}) == len(CHAINS)
        assert len({c.chain_id for c in CHAINS}) == len(CHAINS)

    def test_usdg_is_robinhood_and_usdc_is_arbitrum(self):
        assert chain_for_market("WETH/USDG") is ROBINHOOD
        assert chain_for_market("WETH/USDC") is ARBITRUM
        assert chain_for_market("DOGE/USDG") is None


class TestTheActionSchema:
    def test_the_venue_is_filled_in_from_the_market(self):
        assert DexTradeActionConfig(market="WETH/USDG", exit=EXIT).venue == "uniswap_v3_robinhood"
        assert DexTradeActionConfig(market="WETH/USDC", exit=EXIT).venue == "uniswap_v3_arbitrum"

    def test_a_venue_that_disagrees_with_the_market_is_refused(self):
        with pytest.raises(ValidationError, match="trades on uniswap_v3_robinhood"):
            DexTradeActionConfig(market="WETH/USDG", venue="uniswap_v3_arbitrum", exit=EXIT)

    def test_an_agreeing_venue_is_accepted(self):
        action = DexTradeActionConfig(market="WETH/USDG", venue="uniswap_v3_robinhood", exit=EXIT)
        assert action.venue == "uniswap_v3_robinhood"

    def test_a_market_on_no_chain_is_a_422(self):
        with pytest.raises(ValidationError):
            DexTradeActionConfig(market="WBTC/USDG", exit=EXIT)


class TestTheRegistry:
    def test_live_on_robinhood_signs_for_robinhood_against_its_own_factory(self, live):
        venue = registry.venue_for(_intent(), {"owner_key": "0xowner", "mode": "live"}, None)
        assert isinstance(venue, VaultVenue)
        assert venue.chain.chain_id == 4663
        assert venue.chain.rpc_url == live.robinhood_rpc_url
        assert venue.factory == "0x" + "b" * 40
        assert venue.market_asset == ROBINHOOD.markets["WETH/USDG"]
        assert venue.eth_usd_feed == ROBINHOOD.eth_usd_feed

    def test_live_on_arbitrum_is_unchanged(self, live):
        intent = _intent(venue="uniswap_v3_arbitrum", market="WETH/USDC")
        venue = registry.venue_for(intent, {"owner_key": "0xowner", "mode": "live"}, None)
        assert venue.chain.chain_id == 42161
        assert venue.factory == "0x" + "a" * 40

    def test_each_chain_keeps_one_client(self, live):
        account = {"owner_key": "0xowner", "mode": "live"}
        first = registry.venue_for(_intent(), account, None).chain
        again = registry.venue_for(_intent(), account, None).chain
        other = registry.venue_for(_intent(venue="uniswap_v3_arbitrum", market="WETH/USDC"), account, None).chain
        assert first is again
        assert first is not other

    def test_a_chain_without_a_factory_is_refused_by_name(self, live, monkeypatch):
        monkeypatch.setattr(live, "robinhood_vault_factory_address", "")
        with pytest.raises(registry.NoAdapter, match="Robinhood Chain"):
            registry.venue_for(_intent(), {"owner_key": "0xowner", "mode": "live"}, None)
        # And the other chain is untouched by it.
        intent = _intent(venue="uniswap_v3_arbitrum", market="WETH/USDC")
        assert registry.venue_for(intent, {"owner_key": "0xowner", "mode": "live"}, None)

    def test_a_row_whose_venue_and_market_disagree_is_refused(self, live):
        with pytest.raises(VenueRejected, match="not traded on Arbitrum One"):
            registry.venue_for(_intent(venue="uniswap_v3_arbitrum"), {"mode": "live"}, None)

    def test_a_row_with_no_venue_is_routed_by_its_market(self, live):
        venue = registry.venue_for(_intent(venue=None), {"owner_key": "0xowner", "mode": "live"}, None)
        assert venue.chain.chain_id == 4663

    def test_shadow_needs_no_factory_on_either_chain(self, live, monkeypatch):
        monkeypatch.setattr(live, "robinhood_vault_factory_address", "")
        venue = registry.venue_for(_intent(mode="shadow"), {"mode": "shadow"}, None, candles=[])
        assert isinstance(venue, ShadowVenue)


class TestARuleTradesTheCoinItWatches:
    def test_the_wrapped_coin_is_the_coin(self):
        assert base_of("WETH/USDG") == "ETH"
        assert base_of("WBTC/USDC") == "BTC"

    def test_matching_and_mismatching_symbols(self):
        assert trades_symbol("WETH/USDG", "ETHUSDT")
        assert trades_symbol("WBTC/USDC", "btcusdt")
        assert not trades_symbol("WETH/USDG", "BTCUSDT")
        assert not trades_symbol("WBTC/USDC", "ETHUSDT")

    def test_the_gate_refuses_a_btc_rule_armed_on_an_eth_market(self):
        from services.execution.preflight import check

        rule = {"id": "r1", "symbol": "BTCUSDT", "timeframe": "1h", "params": {}}
        job = {
            "status": "done",
            "rule_id": "r1",
            "report": {"meta": {"symbol": "BTCUSDT", "timeframe": "1h"}, "trades": {"unseen": {"n": 1}}},
        }
        result = check(
            rule,
            DexTradeActionConfig(market="WETH/USDG", exit=EXIT),
            job,
            thresholds=PreflightThresholds(),
            now=datetime.now(timezone.utc),
        )
        assert not result.passed
        assert any("can only trade the coin it watches" in r for r in result.reasons)
