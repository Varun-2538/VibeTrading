// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

/// Uniswap v3 SwapRouter02, exact-input single hop only. A vault that can route
/// through one pool per pair does not need the Universal Router's command
/// encoding, and a smaller surface is the point of this contract.
interface ISwapRouter {
    struct ExactInputSingleParams {
        address tokenIn;
        address tokenOut;
        uint24 fee;
        address recipient;
        uint256 amountIn;
        uint256 amountOutMinimum;
        uint160 sqrtPriceLimitX96;
    }

    function exactInputSingle(ExactInputSingleParams calldata params) external payable returns (uint256 amountOut);
}
