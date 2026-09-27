"""
The encoder and the contract have to agree, and this is what notices when they stop.

Every signature in `abi.py` is typed by hand, which is the right trade for nine
functions - but it means a change in the Solidity can leave the executor calling a
selector that no longer exists, and the failure would look like an unexplained revert
in production. So the signatures are parsed back out of the contract source and
compared, and the vault's error list is checked the same way.

`contracts/out/` is build output and gitignored, so the source is the authority here
rather than the compiled ABI.
"""
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.execution.abi import (
    FUNCTIONS,
    VAULT_ERRORS,
    decode,
    encode,
    revert_reason,
    selector,
    signature,
)

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts" / "src"
VAULT = CONTRACTS / "TradingVault.sol"
FACTORY = CONTRACTS / "VaultFactory.sol"

# Functions we call on the vault, as opposed to on a token, a feed or the factory.
VAULT_FUNCTIONS = (
    "openPosition", "closeIfStopped", "closeIfTargetHit", "closeIfExpired",
    "closeByOperator", "position", "openFloor", "closeFloor", "stable", "asset",
    "oracle", "operator", "maxNotional",
)


def declared(source: str) -> dict:
    """
    name -> tuple of argument types, from the Solidity.

    Public state variables generate a getter with no arguments, so an immutable like
    `IERC20 public immutable stable` is a function too - which is exactly how the
    executor reads it.
    """
    found = {}
    for match in re.finditer(r"function\s+(\w+)\s*\(([^)]*)\)", source):
        name, params = match.group(1), match.group(2).strip()
        types = []
        for part in [p.strip() for p in params.split(",") if p.strip()]:
            types.append(part.split()[0])
        found[name] = tuple(types)
    for match in re.finditer(r"^\s*(?:\w[\w\d]*)\s+public\s+(?:immutable\s+)?(\w+)\s*(?:=|;)", source, re.M):
        found.setdefault(match.group(1), ())
    for match in re.finditer(r"^\s*mapping\([^)]*\)\s+public\s+(\w+)\s*;", source, re.M):
        found.setdefault(match.group(1), None)  # arity checked by hand below
    return found


@pytest.fixture(scope="module")
def vault_source() -> str:
    return VAULT.read_text(encoding="utf-8")


def test_the_contract_this_encodes_against_exists(vault_source):
    assert VAULT.is_file() and FACTORY.is_file()
    assert "contract TradingVault" in vault_source


def test_every_vault_call_matches_the_solidity(vault_source):
    """
    The one that catches a renamed or re-typed function. A selector that no longer
    exists reverts in production and looks like a chain problem.
    """
    found = declared(vault_source)
    for name in VAULT_FUNCTIONS:
        assert name in found, f"{name} is not declared in TradingVault.sol"
        expected = FUNCTIONS[name][0]
        if found[name] == ():
            assert expected == (), f"{name} takes no arguments in the contract"
        else:
            assert found[name] == expected, f"{signature(name)} does not match {name}{found[name]}"


def test_the_vaults_position_getter_returns_what_we_decode(vault_source):
    """
    A public struct getter returns its fields in declaration order, and we decode
    eight of them. If the struct grows, the decode has to grow with it - otherwise a
    stop price is read out of the wrong slot, which is the worst possible silent bug.
    """
    struct = vault_source.split("struct Position {")[1].split("}")[0]
    fields = [line.strip().split()[0] for line in struct.splitlines() if line.strip() and ";" in line]
    assert len(fields) == len(FUNCTIONS["position"][1])
    assert fields[0] == "bool" and fields[-1] == "uint64"


def test_every_error_the_vault_can_raise_is_recognised(vault_source):
    """
    Otherwise an operator reading the logs gets four bytes where a reason should be.
    """
    declared_errors = set(re.findall(r"error\s+(\w+)\s*\(\s*\)\s*;", vault_source))
    assert declared_errors, "no errors parsed; the regex has drifted from the source"
    known = set(VAULT_ERRORS.values())
    assert declared_errors <= known, f"unrecognised: {sorted(declared_errors - known)}"


def test_the_factory_lookup_matches_too():
    source = FACTORY.read_text(encoding="utf-8")
    assert "mapping(address => mapping(address => address)) public vaultOf" in source
    assert FUNCTIONS["vaultOf"][0] == ("address", "address")


class TestEncoding:
    def test_a_call_is_a_selector_and_its_arguments(self):
        data = encode("openFloor", 100_000_000)
        assert data.startswith("0x" + selector("openFloor").hex())
        assert len(data) == 2 + 8 + 64  # 0x, selector, one word

    def test_the_wrong_number_of_arguments_is_refused_here(self):
        with pytest.raises(ValueError):
            encode("openPosition", 1, 2)

    def test_a_no_argument_call_is_just_the_selector(self):
        assert encode("closeIfStopped") == "0x" + selector("closeIfStopped").hex()

    def test_decoding_an_empty_answer_raises_rather_than_returning_zeros(self):
        """
        An empty result means the wrong address or a bare revert. Decoding it to zeros
        would present a zero stop price as "no stop".
        """
        with pytest.raises(ValueError):
            decode("openFloor", "0x")

    def test_a_round_trip_through_the_position_getter(self):
        from eth_abi import encode as abi_encode

        raw = abi_encode(
            list(FUNCTIONS["position"][1]),
            [True, 100_000_000, 50_000_000_000_000_000, 200_000_000_000, 190_000_000_000,
             220_000_000_000, 1_700_000_000, 1_700_500_000],
        )
        row = decode("position", "0x" + raw.hex())
        assert row[0] is True and row[4] == 190_000_000_000


class TestRevertReasons:
    def test_a_custom_error_is_named(self):
        for name in ("NotTriggered", "OverCap", "StaleOracle"):
            data = next(k for k, v in VAULT_ERRORS.items() if v == name)
            assert revert_reason(data + "00" * 4) == name

    def test_a_string_revert_is_quoted(self):
        from eth_abi import encode as abi_encode
        from eth_utils import keccak

        payload = keccak(text="Error(string)")[:4] + abi_encode(["string"], ["Too little received"])
        assert revert_reason("0x" + payload.hex()) == "Too little received"

    def test_anything_else_is_still_reported_as_a_revert(self):
        assert revert_reason(None) == "reverted"
        assert revert_reason("0x") == "reverted"
        assert "custom error" in revert_reason("0xdeadbeef")


def test_the_market_addresses_match_the_contracts_address_book():
    """
    `markets.py` duplicates two addresses from Addresses.sol, which is the authority.
    An address that drifted here would be a transaction sent to the wrong token, and
    nothing else in the suite would notice.
    """
    from services.execution.markets import MARKET_ASSETS, USDC

    source = (CONTRACTS / "Addresses.sol").read_text(encoding="utf-8")
    literals = dict(re.findall(r"address internal constant (\w+) = (0x[0-9a-fA-F]{40});", source))
    assert literals, "no addresses parsed; the regex has drifted from the source"
    assert MARKET_ASSETS["WETH/USDC"] == literals["WETH"]
    assert MARKET_ASSETS["WBTC/USDC"] == literals["WBTC"]
    assert USDC == literals["USDC"]


def test_the_default_gas_feed_is_the_one_in_the_address_book():
    from config import settings

    source = (CONTRACTS / "Addresses.sol").read_text(encoding="utf-8")
    literals = dict(re.findall(r"address internal constant (\w+) = (0x[0-9a-fA-F]{40});", source))
    assert settings.eth_usd_feed == literals["ETH_USD"]
