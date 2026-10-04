// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {TradingVault} from "../src/TradingVault.sol";
import {VaultFactory} from "../src/VaultFactory.sol";
import {MockERC20} from "./mocks/MockERC20.sol";
import {MockOracle} from "./mocks/MockOracle.sol";
import {MockRouter} from "./mocks/MockRouter.sol";

/// The cheatcode interface, declared here rather than pulled in as a submodule.
/// Four functions is less to trust than a dependency.
interface Vm {
    function warp(uint256) external;
    function prank(address) external;
    function expectRevert(bytes4) external;
    function expectRevert() external;
}

contract Asserts {
    Vm internal constant vm = Vm(0x7109709ECfa91a80626fF3989D68f67F5b1DD12D);

    function eq(uint256 a, uint256 b, string memory what) internal pure {
        require(a == b, what);
    }

    function isTrue(bool ok, string memory what) internal pure {
        require(ok, what);
    }
}

/// What the operator may do, and everything it may not.
///
/// The vault exists to make a stolen operator key survivable, so most of these
/// tests are about refusals. The ones about the bounty are about the other half of
/// the design: an exit that does not depend on our uptime.
contract TradingVaultTest is Asserts {
    address constant OWNER = address(0xA11CE);
    address constant OPERATOR = address(0xB0B);
    address constant STRANGER = address(0xCAFE);

    uint256 constant PRICE = 2000e8; // $2,000 an ETH
    uint256 constant TVL_CAP = 500e6;
    bytes32 constant DISCLOSURE = keccak256("risk disclosure v1");

    MockERC20 usdc;
    MockERC20 weth;
    MockOracle oracle;
    MockRouter router;
    TradingVault vault;

    function setUp() public {
        usdc = new MockERC20("USDC", 6);
        weth = new MockERC20("WETH", 18);
        oracle = new MockOracle(int256(PRICE), block.timestamp);
        router = new MockRouter();
        router.setPrice(PRICE);

        vault = new TradingVault(
            OWNER, address(usdc), address(weth), address(router), address(oracle), 500, DISCLOSURE, TVL_CAP
        );

        // The router needs stock of both sides to fill a swap.
        weth.mint(address(router), 1000e18);
        usdc.mint(address(router), 1_000_000e6);

        usdc.mint(OWNER, 1000e6);
        vm.prank(OWNER);
        usdc.approve(address(vault), type(uint256).max);
        vm.prank(OWNER);
        vault.deposit(400e6);

        vm.prank(OWNER);
        vault.setOperator(OPERATOR, uint64(block.timestamp + 30 days));
        vm.prank(OWNER);
        vault.setCaps(200e6, 5, 100, 0.2e6);
    }

    function open() internal returns (uint256 qty) {
        // The floor comes from the vault, not from arithmetic repeated here. That
        // is also how the executor will do it.
        uint256 minOut = vault.openFloor(100e6);
        vm.prank(OPERATOR);
        return vault.openPosition(100e6, 1900e8, 2200e8, uint64(block.timestamp + 5 days), minOut);
    }

    function test_the_vault_publishes_its_own_floor() public view {
        // $100 at $2,000 is 0.05 ETH; the owner allowed 1% of slippage.
        eq(vault.openFloor(100e6), 0.0495e18, "the floor the executor must respect");
    }

    // --- what the operator cannot do -----------------------------------------

    function test_operator_cannot_withdraw() public {
        vm.expectRevert(TradingVault.NotOwner.selector);
        vm.prank(OPERATOR);
        vault.withdraw(address(usdc), 1e6, OPERATOR);
    }

    function test_a_stranger_cannot_withdraw_or_grant() public {
        vm.expectRevert(TradingVault.NotOwner.selector);
        vm.prank(STRANGER);
        vault.withdraw(address(usdc), 1e6, STRANGER);

        vm.expectRevert(TradingVault.NotOwner.selector);
        vm.prank(STRANGER);
        vault.setOperator(STRANGER, uint64(block.timestamp + 1 days));
    }

    function test_a_stop_cannot_be_moved_once_written() public {
        open();
        (,,,, uint256 stopPrice,,,) = vault.position();
        eq(stopPrice, 1900e8, "stop as written");
        // There is no setter. The only way to a different stop is a different
        // position, and a second one cannot be opened.
        vm.expectRevert(TradingVault.PositionOpen.selector);
        vm.prank(OPERATOR);
        vault.openPosition(50e6, 1500e8, 2500e8, uint64(block.timestamp + 5 days), 0.0246e18);
    }

    function test_a_trade_over_the_cap_is_refused() public {
        vm.expectRevert(TradingVault.OverCap.selector);
        vm.prank(OPERATOR);
        vault.openPosition(300e6, 1900e8, 2200e8, uint64(block.timestamp + 5 days), 0.14e18);
    }

    function test_the_daily_count_is_a_real_limit_and_resets() public {
        for (uint256 i = 0; i < 5; i++) {
            open();
            vm.prank(OPERATOR);
            vault.closeByOperator();
        }
        vm.expectRevert(TradingVault.TooManyTradesToday.selector);
        vm.prank(OPERATOR);
        vault.openPosition(10e6, 1900e8, 2200e8, uint64(block.timestamp + 5 days), 0.0049e18);

        vm.warp(block.timestamp + 1 days + 1);
        oracle.set(int256(PRICE), block.timestamp);
        open(); // a new day, and the count starts again
    }

    function test_an_expired_grant_stops_the_operator() public {
        vm.warp(block.timestamp + 31 days);
        oracle.set(int256(PRICE), block.timestamp);
        vm.expectRevert(TradingVault.GrantExpired.selector);
        vm.prank(OPERATOR);
        vault.openPosition(100e6, 1900e8, 2200e8, uint64(block.timestamp + 5 days), 0.0494e18);
    }

    function test_revoking_the_grant_is_immediate() public {
        open();
        vm.prank(OWNER);
        vault.revokeOperator();
        vm.expectRevert(TradingVault.NotOperator.selector);
        vm.prank(OPERATOR);
        vault.closeByOperator();
        // And the owner is never stuck with a position because of it.
        vm.prank(OWNER);
        vault.closeByOwner();
    }

    function test_a_stop_on_the_wrong_side_is_refused() public {
        vm.expectRevert(TradingVault.BadPrices.selector);
        vm.prank(OPERATOR);
        vault.openPosition(100e6, 2100e8, 2200e8, uint64(block.timestamp + 5 days), 0.0494e18);

        vm.expectRevert(TradingVault.BadPrices.selector);
        vm.prank(OPERATOR);
        vault.openPosition(100e6, 1900e8, 1950e8, uint64(block.timestamp + 5 days), 0.0494e18);
    }

    function test_a_deadline_must_be_ahead_and_not_absurd() public {
        vm.expectRevert(TradingVault.BadDeadline.selector);
        vm.prank(OPERATOR);
        vault.openPosition(100e6, 1900e8, 2200e8, uint64(block.timestamp), 0.0494e18);

        vm.expectRevert(TradingVault.BadDeadline.selector);
        vm.prank(OPERATOR);
        vault.openPosition(100e6, 1900e8, 2200e8, uint64(block.timestamp + 100 days), 0.0494e18);
    }

    // --- what the owner may always do ----------------------------------------

    function test_the_owner_can_withdraw_while_a_position_is_open() public {
        open();
        uint256 before = usdc.balanceOf(OWNER);
        vm.prank(OWNER);
        vault.withdraw(address(usdc), 100e6, OWNER);
        eq(usdc.balanceOf(OWNER), before + 100e6, "owner took their stable back");
    }

    function test_deposits_stop_at_the_hard_cap() public {
        vm.expectRevert(TradingVault.OverCap.selector);
        vm.prank(OWNER);
        vault.deposit(200e6); // 400 already in, cap is 500
    }

    function test_caps_cannot_be_loosened_past_the_contracts_own_ceiling() public {
        vm.expectRevert(TradingVault.OverCap.selector);
        vm.prank(OWNER);
        vault.setCaps(200e6, 5, 900, 0.2e6); // slippage over 5%

        vm.expectRevert(TradingVault.OverCap.selector);
        vm.prank(OWNER);
        vault.setCaps(200e6, 5, 100, 5e6); // bounty over $2
    }

    // --- exits nobody may fake ------------------------------------------------

    function test_a_stop_that_has_not_been_hit_reverts() public {
        open();
        vm.expectRevert(TradingVault.NotTriggered.selector);
        vm.prank(STRANGER);
        vault.closeIfStopped();
    }

    function test_a_stranger_closes_a_stopped_position_and_is_paid_for_it() public {
        open();
        oracle.set(1850e8, block.timestamp);
        router.setPrice(1850e8);

        uint256 before = usdc.balanceOf(STRANGER);
        vm.prank(STRANGER);
        vault.closeIfStopped();

        (bool stillOpen,,,,,,,) = vault.position();
        isTrue(!stillOpen, "position closed");
        eq(usdc.balanceOf(STRANGER), before + 0.2e6, "the bounty is why this works when we are down");
    }

    function test_we_are_not_paid_a_bounty_out_of_their_vault() public {
        open();
        oracle.set(1850e8, block.timestamp);
        router.setPrice(1850e8);

        uint256 before = usdc.balanceOf(OPERATOR);
        vm.prank(OPERATOR);
        vault.closeIfStopped();
        eq(usdc.balanceOf(OPERATOR), before, "a fee by another name is still a fee");
    }

    function test_a_target_closes_only_when_it_is_reached() public {
        open();
        vm.expectRevert(TradingVault.NotTriggered.selector);
        vm.prank(STRANGER);
        vault.closeIfTargetHit();

        oracle.set(2250e8, block.timestamp);
        router.setPrice(2250e8);
        vm.prank(STRANGER);
        uint256 received = vault.closeIfTargetHit();
        isTrue(received > 100e6, "a target that paid");
    }

    function test_time_runs_out_without_any_price_at_all() public {
        open();
        vm.expectRevert(TradingVault.NotTriggered.selector);
        vm.prank(STRANGER);
        vault.closeIfExpired();

        vm.warp(block.timestamp + 5 days + 1);
        oracle.set(int256(PRICE), block.timestamp);
        vm.prank(STRANGER);
        vault.closeIfExpired();
        (bool stillOpen,,,,,,,) = vault.position();
        isTrue(!stillOpen, "closed on time");
    }

    // --- the oracle, and the sandwich it prevents -----------------------------

    function test_a_stale_feed_authorises_nothing() public {
        vm.warp(block.timestamp + 27 hours);
        vm.expectRevert(TradingVault.StaleOracle.selector);
        vm.prank(OPERATOR);
        vault.openPosition(100e6, 1900e8, 2200e8, uint64(block.timestamp + 5 days), 0.0494e18);
    }

    function test_a_fill_worse_than_the_oracle_allows_is_refused() public {
        // The router hands back 3% less than fair; the owner allowed 1%.
        uint256 minOut = vault.openFloor(100e6);
        router.setFill(9700);
        // Any revert: in practice Uniswap's router refuses first, on the minimum we
        // hand it. The next test covers the case where it does not.
        vm.expectRevert();
        vm.prank(OPERATOR);
        vault.openPosition(100e6, 1900e8, 2200e8, uint64(block.timestamp + 5 days), minOut);
    }

    function test_a_stranger_cannot_sandwich_the_exit_they_trigger() public {
        open();
        oracle.set(1850e8, block.timestamp);
        // The pool is where the caller wants it, not where the oracle says.
        router.setPrice(1850e8);
        router.setFill(9000);
        vm.expectRevert();
        vm.prank(STRANGER);
        vault.closeIfStopped();
    }

    function test_the_vault_checks_the_fill_itself_even_if_the_router_does_not() public {
        /// The oracle floor is the vault's own guarantee, not something it borrows
        /// from the router. A router that under-delivers silently - a bug, or a
        /// different router behind the same interface - still cannot take the
        /// difference.
        router.setLie(true);
        router.setFill(9700);
        uint256 minOut = vault.openFloor(100e6);
        vm.expectRevert(TradingVault.Slippage.selector);
        vm.prank(OPERATOR);
        vault.openPosition(100e6, 1900e8, 2200e8, uint64(block.timestamp + 5 days), minOut);
    }

    function test_closing_nothing_is_not_an_exit() public {
        vm.expectRevert(TradingVault.NoPosition.selector);
        vm.prank(STRANGER);
        vault.closeIfStopped();
    }

    function test_the_disclosure_the_owner_accepted_is_on_chain() public view {
        eq(uint256(vault.disclosure()), uint256(DISCLOSURE), "which wording they agreed to");
    }
}

/// The factory fixes what a vault points at, so a vault deployed somewhere else
/// cannot be presented as one of ours.
contract VaultFactoryTest is Asserts {
    MockERC20 usdc;
    MockERC20 weth;
    MockOracle oracle;
    MockRouter router;
    VaultFactory factory;

    function setUp() public {
        usdc = new MockERC20("USDC", 6);
        weth = new MockERC20("WETH", 18);
        oracle = new MockOracle(2000e8, block.timestamp);
        router = new MockRouter();

        VaultFactory.Market[] memory markets = new VaultFactory.Market[](1);
        markets[0] = VaultFactory.Market({asset: address(weth), oracle: address(oracle), poolFee: 500});
        factory = new VaultFactory(address(usdc), address(router), markets);
    }

    function test_a_deployed_vault_points_where_the_factory_says() public {
        address vault = factory.deploy(address(weth), keccak256("v1"));
        TradingVault v = TradingVault(vault);
        eq(uint256(uint160(address(v.owner()))), uint256(uint160(address(this))), "owner is the caller");
        eq(uint256(uint160(address(v.router()))), uint256(uint160(address(router))), "router is fixed");
        eq(uint256(uint160(address(v.oracle()))), uint256(uint160(address(oracle))), "oracle is fixed");
        eq(v.tvlCap(), factory.TVL_CAP(), "the cap is the factory's constant");
        eq(factory.TVL_CAP(), 500e6, "and it is five hundred dollars until an audit");
    }

    function test_an_unknown_asset_is_refused() public {
        MockERC20 doge = new MockERC20("DOGE", 18);
        vm.expectRevert(VaultFactory.UnknownAsset.selector);
        factory.deploy(address(doge), keccak256("v1"));
    }

    function test_consent_cannot_be_empty() public {
        vm.expectRevert(VaultFactory.NoDisclosure.selector);
        factory.deploy(address(weth), bytes32(0));
    }

    function test_one_vault_per_owner_per_market() public {
        factory.deploy(address(weth), keccak256("v1"));
        vm.expectRevert(VaultFactory.AlreadyDeployed.selector);
        factory.deploy(address(weth), keccak256("v1"));
    }
}
