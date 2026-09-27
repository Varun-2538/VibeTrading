// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

/// Chainlink price feed. Only latestRoundData is used, and its updatedAt is
/// checked: a stale feed must not be able to authorise an exit.
interface IAggregatorV3 {
    function decimals() external view returns (uint8);
    function latestRoundData()
        external
        view
        returns (uint80 roundId, int256 answer, uint256 startedAt, uint256 updatedAt, uint80 answeredInRound);
}
