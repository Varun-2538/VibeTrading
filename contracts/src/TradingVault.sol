// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {IAggregatorV3} from "./interfaces/IAggregatorV3.sol";
import {IERC20} from "./interfaces/IERC20.sol";
import {ISwapRouter} from "./interfaces/ISwapRouter.sol";

/// @title TradingVault
/// @notice One user's vault. It holds their stablecoins, it can swap them into one
///         whitelisted asset and back, and it can do nothing else.
///
/// The point of this contract is what the operator *cannot* do. We run the bot, so
/// we hold an operator key; a compromise of that key must not be able to take
/// anything. There is no transfer, no arbitrary approve, no way to change the
/// router, the oracle or the asset, and no way to move a stop once it is set - not
/// for the operator, and not for the owner either.
///
/// Exits are permissionless. A contract cannot notice a price: EVM code only runs
/// when a transaction calls it, so something outside has to push the button. Our
/// executor normally does, within seconds. If it is down, anyone can call
/// closeIfStopped, closeIfTargetHit or closeIfExpired and collect a small bounty -
/// the same incentive that makes lending liquidations reliable without trusting any
/// one operator. Each of those calls reverts unless the condition is genuinely
/// true, so a stranger cannot invent an exit; the oracle decides *whether* an exit
/// is allowed, and an oracle-derived minimum out stops the caller routing the swap
/// through a manipulated pool and keeping the difference.
///
/// One asset, one position at a time, on purpose. A vault per pair is easier to
/// reason about than a vault with a portfolio in it, and the backtester this is
/// measured against also holds one position at a time.
contract TradingVault {
    // --- immutable: the whole security argument lives here ---------------------

    address public immutable owner;
    IERC20 public immutable stable; // what the vault holds when it is flat
    IERC20 public immutable asset; // what a position is held in
    ISwapRouter public immutable router;
    IAggregatorV3 public immutable oracle; // asset priced in USD
    uint24 public immutable poolFee;
    /// keccak256 of the risk disclosure the owner accepted when this was deployed.
    /// A timestamped, on-chain record of which text they agreed to.
    bytes32 public immutable disclosure;
    /// The most this vault may ever hold. Set by the factory from a constant, so
    /// raising it means deploying a new vault - nobody, including us, can raise it
    /// here. It comes off before the audit, not before.
    uint256 public immutable tvlCap;

    uint8 private immutable stableDecimals;
    uint8 private immutable assetDecimals;
    uint8 private immutable oracleDecimals;

    // --- limits, all of them ceilings the owner can only tighten --------------

    uint16 public constant MAX_SLIPPAGE_BPS = 500; // 5%
    uint256 public constant MAX_BOUNTY = 2e6; // $2, in the stable's six decimals (USDC, USDG)
    uint64 public constant MAX_POSITION_AGE = 45 days;
    /// The Chainlink feeds we use update on a small deviation (0.05% on Arbitrum
    /// One, 0.5% on Robinhood Chain) or a daily heartbeat, so anything older than a day and change means the feed is broken
    /// rather than quiet. Tighter than this would make exits impossible in a calm
    /// market, which is worse than the risk it would remove.
    uint256 public constant MAX_ORACLE_AGE = 26 hours;

    // --- the operator grant, entirely the owner's to give and take ------------

    address public operator;
    uint64 public operatorExpiry;
    uint256 public maxNotional; // per trade, in stable units
    uint16 public maxTradesPerDay;
    uint16 public maxSlippageBps;
    uint256 public bounty; // flat, in stable units, to a stranger who closes

    uint64 public dayStart;
    uint16 public tradesToday;

    // --- the one position ------------------------------------------------------

    struct Position {
        bool open;
        uint256 spent; // stable put in
        uint256 qty; // asset held
        uint256 entryPrice; // oracle price at open
        uint256 stopPrice; // written once, never mutable
        uint256 targetPrice; // 0 means none
        uint64 openedAt;
        uint64 deadline;
    }

    Position public position;

    bool private entered;

    // --- events: the audit trail is on-chain too -------------------------------

    event Deposited(uint256 amount, uint256 balance);
    event Withdrawn(address token, uint256 amount, address to);
    event OperatorSet(address operator, uint64 expiry);
    event CapsSet(uint256 maxNotional, uint16 maxTradesPerDay, uint16 maxSlippageBps, uint256 bounty);
    event Opened(
        uint256 spent, uint256 qty, uint256 entryPrice, uint256 stopPrice, uint256 targetPrice, uint64 deadline
    );
    event Closed(string reason, uint256 qty, uint256 received, uint256 price, address closedBy, uint256 bountyPaid);

    error NotOwner();
    error NotOperator();
    error GrantExpired();
    error PositionOpen();
    error NoPosition();
    error OverCap();
    error TooManyTradesToday();
    error BadPrices();
    error BadDeadline();
    error StaleOracle();
    error NotTriggered();
    error Slippage();
    error Reentrancy();
    error TransferFailed();

    modifier onlyOwner() {
        if (msg.sender != owner) revert NotOwner();
        _;
    }

    modifier onlyOperator() {
        if (msg.sender != operator) revert NotOperator();
        if (block.timestamp > operatorExpiry) revert GrantExpired();
        _;
    }

    modifier nonReentrant() {
        if (entered) revert Reentrancy();
        entered = true;
        _;
        entered = false;
    }

    constructor(
        address _owner,
        address _stable,
        address _asset,
        address _router,
        address _oracle,
        uint24 _poolFee,
        bytes32 _disclosure,
        uint256 _tvlCap
    ) {
        owner = _owner;
        stable = IERC20(_stable);
        asset = IERC20(_asset);
        router = ISwapRouter(_router);
        oracle = IAggregatorV3(_oracle);
        poolFee = _poolFee;
        disclosure = _disclosure;
        tvlCap = _tvlCap;

        stableDecimals = IERC20(_stable).decimals();
        assetDecimals = IERC20(_asset).decimals();
        oracleDecimals = IAggregatorV3(_oracle).decimals();

        // Deliberately not armed by deployment: the owner grants the operator in a
        // separate transaction, so funding a vault and authorising a bot are two
        // decisions rather than one.
        maxSlippageBps = 50;
        maxTradesPerDay = 5;
        dayStart = uint64(block.timestamp);
    }

    // --- the owner's rights, none of which anyone can block -------------------

    function deposit(uint256 amount) external {
        _pull(amount);
        uint256 balance = stable.balanceOf(address(this));
        if (balance > tvlCap) revert OverCap();
        emit Deposited(amount, balance);
    }

    /// Always available, position open or not. If a position is open the asset is
    /// still the owner's to take; taking it is what closeByOwner is for, and this
    /// works either way.
    function withdraw(address token, uint256 amount, address to) external onlyOwner {
        _check(IERC20(token).transfer(to, amount));
        emit Withdrawn(token, amount, to);
    }

    function setOperator(address who, uint64 expiry) external onlyOwner {
        operator = who;
        operatorExpiry = expiry;
        emit OperatorSet(who, expiry);
    }

    /// The one call the owner may always make, whatever we are doing.
    function revokeOperator() external onlyOwner {
        operator = address(0);
        operatorExpiry = 0;
        emit OperatorSet(address(0), 0);
    }

    function setCaps(uint256 _maxNotional, uint16 _maxTradesPerDay, uint16 _maxSlippageBps, uint256 _bounty)
        external
        onlyOwner
    {
        if (_maxSlippageBps > MAX_SLIPPAGE_BPS || _bounty > MAX_BOUNTY) revert OverCap();
        maxNotional = _maxNotional;
        maxTradesPerDay = _maxTradesPerDay;
        maxSlippageBps = _maxSlippageBps;
        bounty = _bounty;
        emit CapsSet(_maxNotional, _maxTradesPerDay, _maxSlippageBps, _bounty);
    }

    // --- what the operator may do, and only this ------------------------------

    /// @notice Swap stable into the asset, and write where it gets out.
    /// @dev The stop, the target and the deadline are stored here and there is no
    ///      function anywhere that changes them. That is the feature: a bot cannot
    ///      give a losing position "a little more room", and neither can we.
    function openPosition(uint256 amountIn, uint256 stopPrice, uint256 targetPrice, uint64 deadline, uint256 minOut)
        external
        onlyOperator
        nonReentrant
        returns (uint256 qty)
    {
        if (position.open) revert PositionOpen();
        if (amountIn == 0 || amountIn > maxNotional) revert OverCap();
        if (deadline <= block.timestamp || deadline > block.timestamp + MAX_POSITION_AGE) revert BadDeadline();

        uint256 price = _price();
        // A long: the stop is below, the target - if there is one - is above. A
        // stop on the wrong side would be hit by the next call to closeIfStopped.
        if (stopPrice == 0 || stopPrice >= price) revert BadPrices();
        if (targetPrice != 0 && targetPrice <= price) revert BadPrices();

        _countTrade();

        uint256 floor = _minOut(amountIn, stableDecimals, assetDecimals, price, true);
        if (minOut < floor) revert Slippage();

        qty = _swap(address(stable), address(asset), amountIn, minOut);

        position = Position({
            open: true,
            spent: amountIn,
            qty: qty,
            entryPrice: price,
            stopPrice: stopPrice,
            targetPrice: targetPrice,
            openedAt: uint64(block.timestamp),
            deadline: deadline
        });
        emit Opened(amountIn, qty, price, stopPrice, targetPrice, deadline);
    }

    /// An exit the strategy asked for that no oracle can verify: an opposing
    /// signal, or the owner's kill switch reaching us. Safe to allow, because the
    /// proceeds can only land back in this vault.
    function closeByOperator() external onlyOperator nonReentrant returns (uint256 received) {
        return _close("operator", false);
    }

    function closeByOwner() external onlyOwner nonReentrant returns (uint256 received) {
        return _close("owner", false);
    }

    // --- exits anyone may push, and nobody may fake ---------------------------

    function closeIfStopped() external nonReentrant returns (uint256 received) {
        if (!position.open) revert NoPosition();
        if (_price() > position.stopPrice) revert NotTriggered();
        return _close("stop", true);
    }

    function closeIfTargetHit() external nonReentrant returns (uint256 received) {
        if (!position.open) revert NoPosition();
        if (position.targetPrice == 0 || _price() < position.targetPrice) revert NotTriggered();
        return _close("target", true);
    }

    function closeIfExpired() external nonReentrant returns (uint256 received) {
        if (!position.open) revert NoPosition();
        if (block.timestamp < position.deadline) revert NotTriggered();
        return _close("time", true);
    }

    // --- views ----------------------------------------------------------------

    /// The least a swap of `amountIn` stable may return, at the current oracle
    /// price and the owner's slippage. Published so the executor asks the vault
    /// what the floor is instead of computing its own and disagreeing.
    function openFloor(uint256 amountIn) external view returns (uint256) {
        return _minOut(amountIn, stableDecimals, assetDecimals, _price(), true);
    }

    /// The least closing the open position may return, on the same terms.
    function closeFloor() external view returns (uint256) {
        if (!position.open) revert NoPosition();
        return _minOut(position.qty, assetDecimals, stableDecimals, _price(), false);
    }

    function stopTriggered() external view returns (bool) {
        return position.open && _price() <= position.stopPrice;
    }

    function targetTriggered() external view returns (bool) {
        return position.open && position.targetPrice != 0 && _price() >= position.targetPrice;
    }

    function expired() external view returns (bool) {
        return position.open && block.timestamp >= position.deadline;
    }

    // --- internals ------------------------------------------------------------

    function _pull(uint256 amount) private {
        _check(stable.transferFrom(msg.sender, address(this), amount));
    }

    /// A token that returns false instead of reverting must not pass for a transfer
    /// that happened. USDC reverts, but the vault does not get to assume its token.
    function _check(bool ok) private pure {
        if (!ok) revert TransferFailed();
    }

    /// The oracle price, or a revert. A feed that has stopped updating must not be
    /// able to authorise anything, in either direction.
    function _price() private view returns (uint256) {
        (, int256 answer,, uint256 updatedAt,) = oracle.latestRoundData();
        if (answer <= 0) revert StaleOracle();
        if (updatedAt == 0 || block.timestamp - updatedAt > MAX_ORACLE_AGE) revert StaleOracle();
        // Safe: the check above refuses anything that is not strictly positive.
        // forge-lint: disable-next-line(unsafe-typecast)
        return uint256(answer);
    }

    /// What a swap should return at the oracle price, less the slippage the owner
    /// allows. This is what stops a permissionless caller sandwiching the exit: the
    /// swap either clears the oracle's idea of fair, or it reverts.
    function _minOut(uint256 amountIn, uint8 inDecimals, uint8 outDecimals, uint256 price, bool buyingAsset)
        private
        view
        returns (uint256)
    {
        uint256 scale = 10 ** oracleDecimals;
        uint256 expected;
        if (buyingAsset) {
            // stable in, asset out: divide by price
            expected = (amountIn * scale * (10 ** outDecimals)) / (price * (10 ** inDecimals));
        } else {
            // asset in, stable out: multiply by price
            expected = (amountIn * price * (10 ** outDecimals)) / (scale * (10 ** inDecimals));
        }
        return (expected * (10_000 - maxSlippageBps)) / 10_000;
    }

    function _countTrade() private {
        if (block.timestamp >= dayStart + 1 days) {
            dayStart = uint64(block.timestamp);
            tradesToday = 0;
        }
        if (tradesToday + 1 > maxTradesPerDay) revert TooManyTradesToday();
        tradesToday += 1;
    }

    function _swap(address tokenIn, address tokenOut, uint256 amountIn, uint256 minOut) private returns (uint256) {
        // Approved for exactly this swap, never left standing. The router is
        // immutable, so this is the only spender that ever exists.
        _check(IERC20(tokenIn).approve(address(router), amountIn));
        uint256 out = router.exactInputSingle(
            ISwapRouter.ExactInputSingleParams({
                tokenIn: tokenIn,
                tokenOut: tokenOut,
                fee: poolFee,
                recipient: address(this),
                amountIn: amountIn,
                amountOutMinimum: minOut,
                sqrtPriceLimitX96: 0
            })
        );
        _check(IERC20(tokenIn).approve(address(router), 0));
        if (out < minOut) revert Slippage();
        return out;
    }

    function _close(string memory reason, bool payBounty) private returns (uint256 received) {
        if (!position.open) revert NoPosition();
        uint256 qty = position.qty;
        uint256 price = _price();

        // Cleared before the swap: a router that called back into this contract
        // must not find a position it can close twice.
        delete position;

        uint256 floor = _minOut(qty, assetDecimals, stableDecimals, price, false);
        received = _swap(address(asset), address(stable), qty, floor);

        uint256 paid = 0;
        // A stranger who pushes the button is paid for it; we are not, and neither
        // is the owner. Paying ourselves out of their vault for work we said we
        // would do would be a fee by another name.
        if (payBounty && bounty > 0 && msg.sender != operator && msg.sender != owner) {
            paid = bounty > received ? received : bounty;
            _check(stable.transfer(msg.sender, paid));
        }
        emit Closed(reason, qty, received, price, msg.sender, paid);
    }
}
