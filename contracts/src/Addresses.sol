// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

/// Mainnet addresses, in one place, so nothing else in the repo carries a literal.
///
/// Every one of these is asserted by test/Fork.t.sol against a live node before it
/// is ever deployed against: the fork test reads decimals off the tokens and a
/// round off each feed, which is the check that catches a transposed address. Do
/// not deploy from these without that test passing - an address that is wrong here
/// is a vault pointing at somebody else's contract.
library ArbitrumOne {
    uint256 internal constant CHAIN_ID = 42161;

    address internal constant USDC = 0xaf88d065e77c8cC2239327C5EDb3A432268e5831;
    address internal constant WETH = 0x82aF49447D8a07e3bd95BD0d56f35241523fBab1;
    address internal constant WBTC = 0x2f2a2543B76A4166549F7aaB2e75Bef0aefC5B0f;

    /// Uniswap v3 SwapRouter02.
    address internal constant SWAP_ROUTER = 0x68b3465833fb72A70ecDF485E0e4C7bD8665Fc45;

    /// Chainlink, 8 decimals, daily heartbeat with a 0.05% deviation trigger.
    address internal constant ETH_USD = 0x639Fe6ab55C921f74e7fac1ee960C0B6293ba612;
    address internal constant BTC_USD = 0x6ce185860a4963106506C203335A2910413708e9;

    /// The 0.05% tier, which is where the depth is for these pairs against USDC.
    uint24 internal constant POOL_FEE = 500;
}
