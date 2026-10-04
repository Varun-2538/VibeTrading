// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {ArbitrumOne, RobinhoodChain} from "../src/Addresses.sol";
import {VaultFactory} from "../src/VaultFactory.sol";

interface DeployVm {
    function startBroadcast() external;
    function stopBroadcast() external;
}

/// Deploys the factory, and nothing else. Vaults are deployed by their owners, from
/// the app, so that the owner of a vault is the wallet that asked for it and never
/// an address of ours.
///
///   forge script script/Deploy.s.sol --rpc-url $RPC --private-key $KEY --broadcast
///
/// The chain is read from the RPC, not passed in, so the markets cannot be the
/// other chain's by mistake - and a chain this script does not know is refused
/// rather than given a guess.
///
/// Run test/Fork.t.sol against the same RPC first. The addresses in Addresses.sol
/// are asserted there, and a transposed address here is a vault pointing at a
/// contract that is not the one we meant.
contract Deploy {
    DeployVm internal constant vm = DeployVm(0x7109709ECfa91a80626fF3989D68f67F5b1DD12D);

    error UnsupportedChain(uint256 chainId);

    function run() external returns (address factory) {
        (address stable, address router, VaultFactory.Market[] memory markets) = config(block.chainid);
        vm.startBroadcast();
        factory = address(new VaultFactory(stable, router, markets));
        vm.stopBroadcast();
    }

    function config(uint256 chainId)
        public
        pure
        returns (address stable, address router, VaultFactory.Market[] memory markets)
    {
        if (chainId == ArbitrumOne.CHAIN_ID) {
            markets = new VaultFactory.Market[](2);
            markets[0] = VaultFactory.Market(ArbitrumOne.WETH, ArbitrumOne.ETH_USD, ArbitrumOne.POOL_FEE);
            markets[1] = VaultFactory.Market(ArbitrumOne.WBTC, ArbitrumOne.BTC_USD, ArbitrumOne.POOL_FEE);
            return (ArbitrumOne.USDC, ArbitrumOne.SWAP_ROUTER, markets);
        }
        if (chainId == RobinhoodChain.CHAIN_ID) {
            markets = new VaultFactory.Market[](1);
            markets[0] = VaultFactory.Market(RobinhoodChain.WETH, RobinhoodChain.ETH_USD, RobinhoodChain.POOL_FEE);
            return (RobinhoodChain.USDG, RobinhoodChain.SWAP_ROUTER, markets);
        }
        revert UnsupportedChain(chainId);
    }
}
