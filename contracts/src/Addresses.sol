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

    /// Uniswap v3 SwapRouter02, and the factory it reports - used by the fork test
    /// to find the pool a vault will swap through.
    address internal constant SWAP_ROUTER = 0x68b3465833fb72A70ecDF485E0e4C7bD8665Fc45;
    address internal constant V3_FACTORY = 0x1F98431c8aD98523631AE4a59f267346ea31F984;

    /// Chainlink, 8 decimals, daily heartbeat with a 0.05% deviation trigger.
    address internal constant ETH_USD = 0x639Fe6ab55C921f74e7fac1ee960C0B6293ba612;
    address internal constant BTC_USD = 0x6ce185860a4963106506C203335A2910413708e9;

    /// The 0.05% tier, which is where the depth is for these pairs against USDC.
    uint24 internal constant POOL_FEE = 500;
}

/// Robinhood Chain, an Arbitrum chain that settles to Ethereum. Its dollar is USDG
/// (Paxos), not USDC, and that is the token a vault here is flat in.
///
/// Sources: docs.robinhood.com/chain/contracts (WETH, USDG), Uniswap's v3 deployment
/// list for Robinhood Chain (router), and Chainlink's feed directory for the chain
/// (ETH / USD). The router was cross-checked on chain: its factory() and WETH9()
/// answer with the Uniswap factory and the WETH below.
///
/// ETH only. Stock Tokens have pools and feeds here, but their feeds follow US
/// market hours, and a vault whose oracle goes quiet every weekend cannot honour
/// a stop on a Saturday. That needs its own staleness rule, not this one.
library RobinhoodChain {
    uint256 internal constant CHAIN_ID = 4663;

    address internal constant USDG = 0x5fc5360D0400a0Fd4f2af552ADD042D716F1d168;
    address internal constant WETH = 0x0Bd7D308f8E1639FAb988df18A8011f41EAcAD73;

    /// Uniswap v3 SwapRouter02, and the factory it reports.
    address internal constant SWAP_ROUTER = 0xCaf681a66D020601342297493863E78C959E5cb2;
    address internal constant V3_FACTORY = 0x1f7d7550B1b028f7571E69A784071F0205FD2EfA;

    /// Chainlink, 8 decimals, daily heartbeat with a 0.5% deviation trigger.
    address internal constant ETH_USD = 0x78F3556b67E17Df817D51Ef5a990cDaF09E8d3A9;

    /// The 0.01% tier. Measured on 2026-10-03 it held ~13.4M USDG against the
    /// 0.05% pool's ~3.4M, so it is the deeper pool as well as the cheaper one.
    uint24 internal constant POOL_FEE = 100;
}
