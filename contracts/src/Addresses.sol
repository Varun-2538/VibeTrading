// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

/// Mainnet addresses, in one place, so nothing else in the repo carries a literal.
///
/// Every one of these is asserted by test/Fork.t.sol against a live node before it
/// is ever deployed against: the fork test reads decimals off the tokens and a
/// round off each feed, which is the check that catches a transposed address. Do
/// not deploy from these without that test passing - an address that is wrong here
/// is a vault pointing at somebody else's contract.

/// How long a market's feed may stay silent before its vault refuses to act on it.
library OracleAge {
    /// Crypto feeds trade around the clock and beat at least daily.
    uint32 internal constant CRYPTO = 26 hours;
    /// US stock feeds stop with the market: Friday 8pm to Sunday 8pm New York, and a
    /// day longer over a holiday weekend, after a last answer up to a heartbeat old.
    uint32 internal constant US_EQUITY = 96 hours;
}

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
/// ETH, and Robinhood's Stock Tokens. Each stock is a standard 18-decimal ERC-20
/// with its own Chainlink feed (which folds in the token's split/dividend
/// multiplier) and a Uniswap pool against USDG; the tier below is the deepest one,
/// measured on 2026-10-04. Addresses from api.robinhood.com/rhj/assets and
/// Chainlink's Robinhood feed directory, cross-checked on chain by the fork test.
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

    // Stock Tokens. USDG depth of the chosen pool in the trailing comment.
    address internal constant NVDA = 0xd0601CE157Db5bdC3162BbaC2a2C8aF5320D9EEC;
    address internal constant NVDA_USD = 0x379EC4f7C378F34a1B47E4F3cbeBCbAC3E8E9F15;
    uint24 internal constant NVDA_FEE = 500; // ~2.25M

    address internal constant QQQ = 0xD5f3879160bc7c32ebb4dC785F8a4F505888de68;
    address internal constant QQQ_USD = 0x80901d846d5D7B030F26B480776EE3b29374C2ae;
    uint24 internal constant QQQ_FEE = 500; // ~744k

    address internal constant TSLA = 0x322F0929c4625eD5bAd873c95208D54E1c003b2d;
    address internal constant TSLA_USD = 0x4A1166a659A55625345e9515b32adECea5547C38;
    uint24 internal constant TSLA_FEE = 3000; // ~309k

    address internal constant SPY = 0x117cc2133c37B721F49dE2A7a74833232B3B4C0C;
    address internal constant SPY_USD = 0x319724394D3A0e3669269846abE664Cd621f9f6A;
    uint24 internal constant SPY_FEE = 500; // ~238k

    address internal constant AAPL = 0xaF3D76f1834A1d425780943C99Ea8A608f8a93f9;
    address internal constant AAPL_USD = 0x6B22A786bAa607d76728168703a39Ea9C99f2cD0;
    uint24 internal constant AAPL_FEE = 500; // ~151k
}
