// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {ArbitrumOne, RobinhoodChain} from "../src/Addresses.sol";
import {IAggregatorV3} from "../src/interfaces/IAggregatorV3.sol";
import {IERC20} from "../src/interfaces/IERC20.sol";
import {VaultFactory} from "../src/VaultFactory.sol";
import {TradingVault} from "../src/TradingVault.sol";
import {Deploy} from "../script/Deploy.s.sol";

interface ForkVm {
    function createSelectFork(string calldata urlOrAlias) external returns (uint256);
    function envOr(string calldata name, string calldata defaultValue) external returns (string memory);
    function skip(bool) external;
    function warp(uint256) external;
    function prank(address) external;
    function startPrank(address) external;
    function stopPrank() external;
}

interface IUniswapV3Factory {
    function getPool(address a, address b, uint24 fee) external view returns (address);
}

/// The only tests that can tell whether the addresses in Addresses.sol are the
/// contracts we think they are. Everything else runs against mocks that agree with
/// us by construction.
///
/// They build the factory from Deploy.config(block.chainid) - the same function the
/// deploy script uses - so what passes here is what gets deployed, not a copy of it.
///
/// Each chain is skipped unless its RPC is set, so the offline suite stays offline:
///   ARBITRUM_RPC_URL=https://arb1.arbitrum.io/rpc forge test --match-contract ArbitrumFork -vv
///   ROBINHOOD_RPC_URL=https://rpc.mainnet.chain.robinhood.com forge test --match-contract RobinhoodFork -vv
abstract contract ForkBase {
    ForkVm internal constant vm = ForkVm(0x7109709ECfa91a80626fF3989D68f67F5b1DD12D);

    address internal constant OWNER = address(0xA11CE);
    address internal constant OPERATOR = address(0xB0B);
    address internal constant STRANGER = address(0x5EED);

    function rpcEnv() internal pure virtual returns (string memory);
    function v3Factory() internal pure virtual returns (address);

    address internal stable;
    address internal router;
    VaultFactory.Market[] internal markets;

    function setUp() public {
        string memory url = vm.envOr(rpcEnv(), string(""));
        if (bytes(url).length == 0) {
            vm.skip(true);
            return;
        }
        vm.createSelectFork(url);
        (address s, address r, VaultFactory.Market[] memory m) = new Deploy().config(block.chainid);
        stable = s;
        router = r;
        for (uint256 i = 0; i < m.length; i++) {
            markets.push(m[i]);
        }
    }

    function test_the_stable_has_the_six_decimals_the_vaults_constants_assume() public view {
        // MAX_BOUNTY and TVL_CAP are written in six decimals. A stable with any
        // other count would make a $2 bounty and a $500 cap mean something else.
        require(IERC20(stable).decimals() == 6, "stable is not 6 decimals");
    }

    function test_every_feed_answers_is_fresh_and_is_eight_decimals() public view {
        for (uint256 i = 0; i < markets.length; i++) {
            IAggregatorV3 feed = IAggregatorV3(markets[i].oracle);
            require(feed.decimals() == 8, "feed is not 8 decimals");
            (, int256 answer,, uint256 updatedAt,) = feed.latestRoundData();
            require(answer > 1e8 && answer < 10_000_000e8, "feed answer is out of any sane range");
            require(block.timestamp - updatedAt < 26 hours, "feed is stale on chain");
        }
    }

    function test_every_market_has_a_pool_at_the_configured_fee_and_it_has_depth() public view {
        for (uint256 i = 0; i < markets.length; i++) {
            address pool = IUniswapV3Factory(v3Factory()).getPool(stable, markets[i].asset, markets[i].poolFee);
            require(pool != address(0), "no pool at the configured fee tier");
            // $100k of the stable on the stable side: thin enough to fail if we
            // picked a dead tier, far below any pool we would actually use.
            require(IERC20(stable).balanceOf(pool) > 100_000e6, "pool at the configured tier is too thin");
        }
    }

    /// The whole life of a position against the real router, the real pool and the
    /// real feed: deposit, grant, open, and an exit pushed by somebody who is
    /// neither us nor the owner, paid the bounty for it.
    function test_a_real_round_trip_closed_by_a_stranger() public {
        VaultFactory factory = new VaultFactory(stable, router, markets);
        VaultFactory.Market memory market = markets[0];

        vm.prank(OWNER);
        TradingVault vault = TradingVault(factory.deploy(market.asset, keccak256("risk disclosure v1")));
        require(address(vault.oracle()) == market.oracle, "oracle not wired");
        require(address(vault.router()) == router, "router not wired");

        // Fund the owner from the pool itself, which is the one holder of the
        // stable we know exists on every chain we support.
        address pool = IUniswapV3Factory(v3Factory()).getPool(stable, market.asset, market.poolFee);
        vm.prank(pool);
        require(IERC20(stable).transfer(OWNER, 50e6), "funding failed");

        vm.startPrank(OWNER);
        IERC20(stable).approve(address(vault), 50e6);
        vault.deposit(50e6);
        vault.setCaps(20e6, 5, 50, 1e6);
        vault.setOperator(OPERATOR, uint64(block.timestamp + 30 days));
        vm.stopPrank();

        (, int256 answer,,,) = IAggregatorV3(market.oracle).latestRoundData();
        require(answer > 0, "feed answered a non-positive price");
        // casting to 'uint256' is safe because the line above refuses anything negative
        // forge-lint: disable-next-line(unsafe-typecast)
        uint256 price = uint256(answer);
        uint64 deadline = uint64(block.timestamp + 10 minutes);

        vm.startPrank(OPERATOR);
        uint256 floor = vault.openFloor(20e6);
        uint256 qty = vault.openPosition(20e6, price * 90 / 100, price * 120 / 100, deadline, floor);
        vm.stopPrank();
        require(qty >= floor && qty > 0, "the swap returned less than the vault's own floor");

        // Not before its time, by anyone.
        vm.prank(STRANGER);
        (bool early,) = address(vault).call(abi.encodeCall(TradingVault.closeIfExpired, ()));
        require(!early, "closed before the deadline");

        vm.warp(deadline);
        vm.prank(STRANGER);
        uint256 received = vault.closeIfExpired();

        require(IERC20(stable).balanceOf(STRANGER) == 1e6, "the stranger was not paid the bounty");
        // Two pool fees and a little price movement: the round trip must come back
        // close to whole. Two percent is far looser than either tier costs.
        require(received > 19.6e6, "the round trip lost more than any fee tier explains");
        require(IERC20(stable).balanceOf(address(vault)) == 30e6 + received - 1e6, "vault balance does not add up");
    }
}

contract ArbitrumForkTest is ForkBase {
    function rpcEnv() internal pure override returns (string memory) {
        return "ARBITRUM_RPC_URL";
    }

    function v3Factory() internal pure override returns (address) {
        return ArbitrumOne.V3_FACTORY;
    }
}

contract RobinhoodForkTest is ForkBase {
    function rpcEnv() internal pure override returns (string memory) {
        return "ROBINHOOD_RPC_URL";
    }

    function v3Factory() internal pure override returns (address) {
        return RobinhoodChain.V3_FACTORY;
    }
}
