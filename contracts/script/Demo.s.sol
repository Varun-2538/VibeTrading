// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {IAggregatorV3} from "../src/interfaces/IAggregatorV3.sol";
import {TradingVault} from "../src/TradingVault.sol";

interface DemoVm {
    function startBroadcast() external;
    function stopBroadcast() external;
    function envAddress(string calldata name) external returns (address);
    function envOr(string calldata name, uint256 defaultValue) external returns (uint256);
}

/// A hand-driven walk through one position, for a recorded demo.
///
/// In production an entry comes from a rule firing and the executor picking up the
/// intent; waiting for a real signal on camera can take days. So the entry here is
/// sent by hand - **with the executor's own key**, through the same openPosition a
/// signal would reach - and everything after it is the real mechanism, unchanged.
///
///   1. Open, as the operator (the executor key), with a short deadline:
///        VAULT=0x... forge script script/Demo.s.sol:DemoOpen \
///          --rpc-url $RPC --interactives 1 --broadcast
///
///   2. Stop the executor, then once the deadline passes, close it from a wallet
///      that is neither the owner nor the operator. It is paid the vault's bounty:
///        VAULT=0x... forge script script/Demo.s.sol:DemoClose \
///          --rpc-url $RPC --interactives 1 --broadcast
contract DemoOpen {
    DemoVm internal constant vm = DemoVm(0x7109709ECfa91a80626fF3989D68f67F5b1DD12D);

    function run() external returns (uint256 qty) {
        TradingVault vault = TradingVault(vm.envAddress("VAULT"));
        // Ten dollars, in the stable's six decimals, unless AMOUNT says otherwise.
        uint256 amountIn = vm.envOr("AMOUNT", uint256(10e6));
        // Minutes until anyone may close it. Ten is long enough to show it refusing
        // an early close, short enough to film.
        uint256 minutes_ = vm.envOr("MINUTES", uint256(10));

        (, int256 answer,,,) = IAggregatorV3(address(vault.oracle())).latestRoundData();
        require(answer > 0, "feed answered a non-positive price");
        // casting to 'uint256' is safe because the line above refuses anything negative
        // forge-lint: disable-next-line(unsafe-typecast)
        uint256 price = uint256(answer);

        // A stop 10% under and a target 20% over: wide enough that only the deadline
        // can end this one, so the demo shows the time exit, which needs no price move.
        uint256 stop = price * 90 / 100;
        uint256 target = price * 120 / 100;
        // casting to 'uint64' is safe because a timestamp plus minutes fits for millennia
        // forge-lint: disable-next-line(unsafe-typecast)
        uint64 deadline = uint64(block.timestamp + minutes_ * 60);

        vm.startBroadcast();
        // The vault's own floor, so the swap is bounded exactly as the executor's is.
        qty = vault.openPosition(amountIn, stop, target, deadline, vault.openFloor(amountIn));
        vm.stopBroadcast();
    }
}

contract DemoClose {
    DemoVm internal constant vm = DemoVm(0x7109709ECfa91a80626fF3989D68f67F5b1DD12D);

    function run() external returns (uint256 received) {
        TradingVault vault = TradingVault(vm.envAddress("VAULT"));
        require(vault.expired(), "not expired yet: the vault would refuse this, and so do we");
        vm.startBroadcast();
        received = vault.closeIfExpired();
        vm.stopBroadcast();
    }
}
