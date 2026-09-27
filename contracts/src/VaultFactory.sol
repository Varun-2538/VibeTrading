// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {TradingVault} from "./TradingVault.sol";

/// @title VaultFactory
/// @notice Deploys one vault per (owner, asset) and remembers where it went.
///
/// The router, the oracle and the pool fee are fixed here rather than chosen by the
/// caller, so a vault cannot be deployed pointing at a contract of somebody's
/// choosing and then presented as one of ours. The asset list is fixed for the same
/// reason: two markets, both with deep Arbitrum pools and a Chainlink feed.
///
/// TVL_CAP is a constant, not a parameter. Raising it means deploying a new factory,
/// which is the intended cost of raising it before the contract has been audited.
contract VaultFactory {
    /// The most any vault deployed by this factory may hold, in USDC's six
    /// decimals. Five hundred dollars: enough to trade honestly, little enough that
    /// a bug in an unaudited contract is a bad week rather than a ruin.
    uint256 public constant TVL_CAP = 500e6;

    address public immutable stable; // USDC
    address public immutable router; // Uniswap SwapRouter02

    struct Market {
        address asset;
        address oracle;
        uint24 poolFee;
    }

    /// asset => its feed and pool. Set once at deployment; there is no setter.
    mapping(address => Market) public markets;
    address[] public assets;

    /// owner => asset => vault. One vault per pair, so a position is never
    /// competing with another position for the same balance.
    mapping(address => mapping(address => address)) public vaultOf;

    event VaultDeployed(address indexed owner, address indexed asset, address vault, bytes32 disclosure);

    error UnknownAsset();
    error AlreadyDeployed();
    error NoDisclosure();

    constructor(address _stable, address _router, Market[] memory _markets) {
        stable = _stable;
        router = _router;
        for (uint256 i = 0; i < _markets.length; i++) {
            markets[_markets[i].asset] = _markets[i];
            assets.push(_markets[i].asset);
        }
    }

    /// @param asset which market this vault trades
    /// @param disclosure keccak256 of the risk text the owner is accepting, stored
    ///        on the vault. Not decoration: it is the record of *which* wording
    ///        they agreed to, timestamped by the block, and it cannot be zero.
    function deploy(address asset, bytes32 disclosure) external returns (address vault) {
        Market memory market = markets[asset];
        if (market.asset == address(0)) revert UnknownAsset();
        if (disclosure == bytes32(0)) revert NoDisclosure();
        if (vaultOf[msg.sender][asset] != address(0)) revert AlreadyDeployed();

        vault = address(
            new TradingVault(msg.sender, stable, asset, router, market.oracle, market.poolFee, disclosure, TVL_CAP)
        );
        vaultOf[msg.sender][asset] = vault;
        emit VaultDeployed(msg.sender, asset, vault, disclosure);
    }

    function marketCount() external view returns (uint256) {
        return assets.length;
    }
}
