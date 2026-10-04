// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {MockERC20} from "./MockERC20.sol";

/// Fills at a price this test sets, so a swap can be made to come back worse than
/// the oracle's idea of fair - which is the case the vault's minimum-out exists for.
contract MockRouter {
    struct ExactInputSingleParams {
        address tokenIn;
        address tokenOut;
        uint24 fee;
        address recipient;
        uint256 amountIn;
        uint256 amountOutMinimum;
        uint160 sqrtPriceLimitX96;
    }

    /// Basis points of the amount the router hands back, against a 1:1 rate scaled
    /// by the decimals difference. 10_000 is "exactly the oracle price".
    uint256 public fillBps = 10_000;
    uint256 public price = 2000e8; // asset/USD, oracle decimals
    uint256 public calls;
    /// When true the router does not enforce the minimum it was handed, so the
    /// vault's own check is the only thing left standing.
    bool public lie;

    function setLie(bool on) external {
        lie = on;
    }

    function setFill(uint256 bps) external {
        fillBps = bps;
    }

    function setPrice(uint256 _price) external {
        price = _price;
    }

    function exactInputSingle(ExactInputSingleParams calldata p) external returns (uint256 amountOut) {
        calls += 1;
        MockERC20 tokenIn = MockERC20(p.tokenIn);
        MockERC20 tokenOut = MockERC20(p.tokenOut);
        uint256 inDec = 10 ** tokenIn.decimals();
        uint256 outDec = 10 ** tokenOut.decimals();

        // Which way round is this? The cheaper token by decimals tells us nothing,
        // so the test says: whichever token has 6 decimals is the stable one.
        bool buyingAsset = tokenIn.decimals() == 6;
        if (buyingAsset) {
            amountOut = (p.amountIn * 1e8 * outDec) / (price * inDec);
        } else {
            amountOut = (p.amountIn * price * outDec) / (1e8 * inDec);
        }
        amountOut = (amountOut * fillBps) / 10_000;

        require(tokenIn.transferFrom(msg.sender, address(this), p.amountIn), "in");
        require(tokenOut.transfer(p.recipient, amountOut), "out");
        if (!lie) require(amountOut >= p.amountOutMinimum, "min out");
    }
}
