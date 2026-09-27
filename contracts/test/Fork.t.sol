// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {ArbitrumOne} from "../src/Addresses.sol";
import {IAggregatorV3} from "../src/interfaces/IAggregatorV3.sol";
import {IERC20} from "../src/interfaces/IERC20.sol";
import {VaultFactory} from "../src/VaultFactory.sol";
import {TradingVault} from "../src/TradingVault.sol";

interface ForkVm {
    function createSelectFork(string calldata urlOrAlias) external returns (uint256);
    function envOr(string calldata name, string calldata defaultValue) external returns (string memory);
    function skip(bool) external;
    function warp(uint256) external;
    function prank(address) external;
}

/// The only test that can tell whether the addresses in Addresses.sol are the
/// contracts we think they are. Everything else runs against mocks that agree with
/// us by construction.
///
/// Skipped unless ARBITRUM_RPC_URL is set, so the offline suite stays offline:
///   ARBITRUM_RPC_URL=https://arb1... forge test --match-path test/Fork.t.sol -vv
contract ForkTest {
    ForkVm internal constant vm = ForkVm(0x7109709ECfa91a80626fF3989D68f67F5b1DD12D);

    bool internal live;

    function setUp() public {
        string memory url = vm.envOr("ARBITRUM_RPC_URL", string(""));
        if (bytes(url).length == 0) {
            vm.skip(true);
            return;
        }
        vm.createSelectFork(url);
        live = true;
    }

    function test_the_tokens_are_the_tokens_we_think_they_are() public view {
        require(IERC20(ArbitrumOne.USDC).decimals() == 6, "USDC is not 6 decimals");
        require(IERC20(ArbitrumOne.WETH).decimals() == 18, "WETH is not 18 decimals");
        require(IERC20(ArbitrumOne.WBTC).decimals() == 8, "WBTC is not 8 decimals");
    }

    function test_both_feeds_answer_and_are_fresh() public view {
        _feed(ArbitrumOne.ETH_USD, 100e8, 100_000e8);
        _feed(ArbitrumOne.BTC_USD, 1_000e8, 1_000_000e8);
    }

    function test_a_factory_deploys_a_vault_wired_to_the_real_thing() public {
        VaultFactory.Market[] memory markets = new VaultFactory.Market[](2);
        markets[0] = VaultFactory.Market(ArbitrumOne.WETH, ArbitrumOne.ETH_USD, ArbitrumOne.POOL_FEE);
        markets[1] = VaultFactory.Market(ArbitrumOne.WBTC, ArbitrumOne.BTC_USD, ArbitrumOne.POOL_FEE);
        VaultFactory factory = new VaultFactory(ArbitrumOne.USDC, ArbitrumOne.SWAP_ROUTER, markets);

        address vault = factory.deploy(ArbitrumOne.WETH, keccak256("risk disclosure v1"));
        TradingVault v = TradingVault(vault);
        require(address(v.oracle()) == ArbitrumOne.ETH_USD, "oracle not wired");
        require(address(v.router()) == ArbitrumOne.SWAP_ROUTER, "router not wired");
        // A live feed, read through the vault's own staleness rules.
        require(v.openFloor(100e6) > 0, "floor unreadable");
    }

    function _feed(address feed, int256 low, int256 high) private view {
        require(IAggregatorV3(feed).decimals() == 8, "feed is not 8 decimals");
        (, int256 answer,, uint256 updatedAt,) = IAggregatorV3(feed).latestRoundData();
        require(answer > low && answer < high, "feed answer is out of any sane range");
        require(block.timestamp - updatedAt < 26 hours, "feed is stale on chain");
    }
}
