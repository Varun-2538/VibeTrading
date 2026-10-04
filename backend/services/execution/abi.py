"""
Calldata for the handful of calls the executor makes.

No web3. `eth_abi` and `eth_utils` are already here as dependencies of eth-account,
which the sign-in path uses, and the whole surface is nine functions - so a library
whose job is to hide the encoding would add a great deal of weight to hide very
little. It would also hide the part that matters: this module and
`contracts/src/TradingVault.sol` have to agree exactly, and a selector computed here
from a signature typed by hand is easier to check against that file than a generated
binding is.

Every signature below is asserted against the contract source by
tests/test_execution_abi.py, which fails if the Solidity changes and this does not.
"""
from typing import Any, Sequence, Tuple

from eth_abi import decode as abi_decode
from eth_abi import encode as abi_encode
from eth_utils import keccak, to_checksum_address

# name -> (argument types, return types)
FUNCTIONS = {
    # TradingVault
    "openPosition": (("uint256", "uint256", "uint256", "uint64", "uint256"), ("uint256",)),
    "closeIfStopped": ((), ("uint256",)),
    "closeIfTargetHit": ((), ("uint256",)),
    "closeIfExpired": ((), ("uint256",)),
    "closeByOperator": ((), ("uint256",)),
    "position": ((), ("bool", "uint256", "uint256", "uint256", "uint256", "uint256", "uint64", "uint64")),
    "openFloor": (("uint256",), ("uint256",)),
    "closeFloor": ((), ("uint256",)),
    "stable": ((), ("address",)),
    "asset": ((), ("address",)),
    "oracle": ((), ("address",)),
    "operator": ((), ("address",)),
    "maxNotional": ((), ("uint256",)),
    # VaultFactory
    "vaultOf": (("address", "address"), ("address",)),
    # Chainlink
    "latestRoundData": ((), ("uint80", "int256", "uint256", "uint256", "uint80")),
    # ERC20
    "balanceOf": (("address",), ("uint256",)),
    "decimals": ((), ("uint8",)),
}


def signature(name: str) -> str:
    args, _ = FUNCTIONS[name]
    return f"{name}({','.join(args)})"


def selector(name: str) -> bytes:
    return keccak(text=signature(name))[:4]


def encode(name: str, *args: Any) -> str:
    """Hex calldata for a call, ready for eth_call or a transaction's data field."""
    types, _ = FUNCTIONS[name]
    if len(args) != len(types):
        raise ValueError(f"{signature(name)} takes {len(types)} arguments, got {len(args)}")
    return "0x" + (selector(name) + abi_encode(list(types), list(args))).hex()


def decode(name: str, data: str) -> Tuple[Any, ...]:
    """
    Decode a return value, or raise on an empty one.

    An empty result usually means the call reverted without a reason, or that the
    address holds no code - both of which have to be loud here rather than silently
    decoding to zeros, because a zero stop price would look like "no stop".
    """
    _, returns = FUNCTIONS[name]
    raw = bytes.fromhex(data[2:] if data.startswith("0x") else data)
    if not raw:
        raise ValueError(f"{name} returned nothing; wrong address, or it reverted")
    return abi_decode(list(returns), raw)


def address(value: str) -> str:
    return to_checksum_address(value)


# Solidity's revert(string) payload, so a refusal can be reported in the words the
# contract used rather than as a hex blob.
ERROR_SELECTOR = keccak(text="Error(string)")[:4]


def revert_reason(data: Any) -> str:
    """
    The reason inside a revert, or a short description of what kind it was.

    A custom error - which is what this vault uses - has no string in it, so the
    best that can be said is its selector. Matched against the vault's own errors by
    name, because "OverCap" tells an operator far more than four bytes.
    """
    if not isinstance(data, str) or not data.startswith("0x") or len(data) < 10:
        return "reverted"
    raw = bytes.fromhex(data[2:])
    if raw[:4] == ERROR_SELECTOR:
        try:
            return abi_decode(["string"], raw[4:])[0]
        except Exception:  # noqa: BLE001 - a malformed reason is still a revert
            return "reverted"
    return VAULT_ERRORS.get("0x" + raw[:4].hex(), "reverted (custom error " + "0x" + raw[:4].hex() + ")")


def _error_selectors(names: Sequence[str]) -> dict:
    return {"0x" + keccak(text=f"{name}()")[:4].hex(): name for name in names}


# Every error TradingVault can raise. Pinned by a test against the contract source,
# so a new error there cannot show up here as four unexplained bytes.
VAULT_ERRORS = _error_selectors(
    (
        "NotOwner",
        "NotOperator",
        "GrantExpired",
        "PositionOpen",
        "NoPosition",
        "OverCap",
        "TooManyTradesToday",
        "BadPrices",
        "BadDeadline",
        "StaleOracle",
        "NotTriggered",
        "Slippage",
        "Reentrancy",
        "TransferFailed",
        "BadOracleAge",
    )
)
