"""
The venue that is a vault, against a scripted chain.

`chain.py` has its own tests for the error mapping, so this fakes that interface and
tests the five steps: ask the vault for its floor, simulate, sign, broadcast once,
read back what happened.

The two properties worth stating plainly, because both are easy to get wrong in a way
that only shows up in money:

- the minimum-out comes from the **vault**, not from our own arithmetic, so it cannot
  be looser than what the contract enforces;
- the fill price is read from the vault afterwards, not inferred from a quote, because
  what a swap returned is a fact about the pool.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
from eth_abi import encode as abi_encode

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from services.execution.abi import FUNCTIONS, selector
from services.execution.chain import Receipt
from services.execution.signer import SignedTransaction
from services.execution.vault_venue import VaultVenue
from services.execution.venue import VenueRejected, VenueUnknown

VAULT = "0x1111111111111111111111111111111111111111"
FACTORY = "0x2222222222222222222222222222222222222222"
OWNER = "0x3333333333333333333333333333333333333333"
ASSET = "0x4444444444444444444444444444444444444444"
STABLE = "0x5555555555555555555555555555555555555555"
ORACLE = "0x6666666666666666666666666666666666666666"
ETH_FEED = "0x7777777777777777777777777777777777777777"


def word(name: str, *values: Any) -> str:
    return "0x" + abi_encode(list(FUNCTIONS[name][1]), list(values)).hex()


class FakeChain:
    """
    Answers by function selector rather than in order, because the venue caches its
    immutable reads and the call sequence is not the thing under test.
    """

    chain_id = 42161

    def __init__(self, answers: Dict[str, Any], *, position_after=None, balance_after=None):
        self.answers = answers
        self.position_after = position_after
        self.balance_after = balance_after
        self.sent: List[str] = []
        self.estimates: List[Dict[str, str]] = []
        self.calls: List[str] = []
        self._writes = 0

    async def call(self, to: str, data: str) -> str:
        sig = data[:10]
        for name, answer in self.answers.items():
            if sig == "0x" + selector(name).hex():
                self.calls.append(name)
                # Some answers change once a write has happened - a position appears,
                # a balance moves - so a callable is asked each time.
                if callable(answer):
                    return answer(self._writes)
                return answer
        raise AssertionError(f"unscripted call {sig} to {to}")

    async def estimate_gas(self, *, frm: str, to: str, data: str) -> int:
        self.estimates.append({"to": to, "data": data})
        if isinstance(self.answers.get("_estimate"), Exception):
            raise self.answers["_estimate"]
        return 300_000

    async def nonce(self, address: str) -> int:
        return 7

    async def gas_price(self) -> int:
        return 100_000_000  # 0.1 gwei, Arbitrum-ish

    async def send_raw(self, signed_hex: str) -> str:
        self.sent.append(signed_hex)
        self._writes += 1
        if isinstance(self.answers.get("_send"), Exception):
            raise self.answers["_send"]
        return "0xhash"

    async def wait_for_receipt(self, tx_hash: str, **kw: Any) -> Receipt:
        if isinstance(self.answers.get("_receipt"), Exception):
            raise self.answers["_receipt"]
        return Receipt(tx_hash=tx_hash, status=1, block_number=100, gas_used=250_000, raw={})


class FakeSigner:
    address = "0x8888888888888888888888888888888888888888"

    def __init__(self) -> None:
        self.signed: List[Dict[str, Any]] = []

    async def sign(self, transaction: Dict[str, Any]) -> SignedTransaction:
        self.signed.append(transaction)
        return SignedTransaction(raw="0xsigned", tx_hash="0xhash", nonce=int(transaction["nonce"]))


def answers(*, position=None, balance=100_000_000, floor=49_500_000_000_000_000, price=2000) -> Dict[str, Any]:
    flat = word("position", False, 0, 0, 0, 0, 0, 0, 0)
    return {
        "stable": word("stable", STABLE),
        "asset": word("asset", ASSET),
        "oracle": word("oracle", ORACLE),
        "decimals": lambda writes: word("decimals", 6),
        "balanceOf": balance if callable(balance) else word("balanceOf", balance),
        "position": position or (lambda writes: flat),
        "openFloor": word("openFloor", floor),
        "closeFloor": word("closeFloor", 0),
        "latestRoundData": word("latestRoundData", 1, price * 10**8, 0, 1_700_000_000, 1),
    }


def venue(chain: FakeChain, *, signer=None, vault: Optional[str] = VAULT, eth_feed=None) -> VaultVenue:
    return VaultVenue(
        chain=chain, signer=signer or FakeSigner(), market="WETH/USDC", vault=vault,
        owner=OWNER, asset=ASSET, factory=FACTORY, eth_usd_feed=eth_feed,
    )


class TestReads:
    async def test_the_quote_is_the_oracles_price_not_the_pools(self):
        """
        It is the price the vault checks a stop against, so triggering on anything else
        would ask the contract for exits it refuses.
        """
        quote = await venue(FakeChain(answers(price=1850))).quote()
        assert quote.price == 1850.0
        assert quote.at == datetime.fromtimestamp(1_700_000_000, tz=timezone.utc)

    async def test_a_broken_feed_is_a_refusal(self):
        chain = FakeChain({**answers(), "latestRoundData": word("latestRoundData", 1, 0, 0, 1, 1)})
        with pytest.raises(VenueRejected):
            await venue(chain).quote()

    async def test_the_balance_is_read_in_the_tokens_own_decimals(self):
        assert await venue(FakeChain(answers(balance=250_000_000))).balance() == 250.0

    async def test_a_flat_vault_reports_no_position(self):
        assert (await venue(FakeChain(answers())).position()).open is False

    async def test_an_open_position_is_scaled_out_of_chain_units(self):
        held = word("position", True, 100_000_000, 5 * 10**16, 200_000_000_000,
                    190_000_000_000, 220_000_000_000, 1_700_000_000, 1_700_500_000)
        chain = FakeChain({**answers(), "position": held, "decimals": lambda w: word("decimals", 6)})
        # The asset's decimals are read from the asset, and here both tokens answer 6,
        # so the qty scales by 1e6 - the point is that it scales at all.
        position = await venue(chain).position()
        assert position.open and position.stop_price == 1900.0 and position.target_price == 2200.0


class TestTarget:
    async def test_the_vault_is_looked_up_in_the_factory(self):
        """
        Not stored on the policy: the factory is the one place that knows which
        contract belongs to an owner, and a stale address would be a transaction sent
        to the wrong contract.
        """
        chain = FakeChain({**answers(), "vaultOf": word("vaultOf", VAULT)})
        assert await venue(chain, vault=None).target() == VAULT

    async def test_an_owner_with_no_vault_is_refused(self):
        chain = FakeChain({**answers(), "vaultOf": word("vaultOf", "0x" + "00" * 20)})
        with pytest.raises(VenueRejected) as exc:
            await venue(chain, vault=None).target()
        assert "no vault" in str(exc.value)

    async def test_nothing_to_look_up_with_is_also_a_refusal(self):
        bare = VaultVenue(chain=FakeChain(answers()), signer=FakeSigner(), market="WETH/USDC")
        with pytest.raises(VenueRejected):
            await bare.target()


class TestOpen:
    def opened(self, qty: int = 5 * 10**16):
        held = word("position", True, 100_000_000, qty, 200_000_000_000,
                    190_000_000_000, 220_000_000_000, 1_700_000_000, 1_700_500_000)
        flat = word("position", False, 0, 0, 0, 0, 0, 0, 0)
        return lambda writes: held if writes else flat

    async def test_the_minimum_out_comes_from_the_vault(self):
        """
        Never from our own arithmetic. A minimum looser than the contract's would let a
        bad fill through; a tighter one would refuse fills the owner already agreed to.
        """
        chain = FakeChain(answers(position=self.opened(), floor=49_000_000_000_000_000))
        signer = FakeSigner()
        await venue(chain, signer=signer).open(
            notional_usd=100.0, stop_price=1900.0, target_price=2200.0,
            deadline=datetime.now(timezone.utc) + timedelta(days=5), min_out=None,
            client_order_id="abc",
        )
        assert "openFloor" in chain.calls
        data = signer.signed[0]["data"]
        assert data.startswith("0x" + selector("openPosition").hex())
        # The floor is the last of the five arguments.
        assert data.endswith(hex(49_000_000_000_000_000)[2:].rjust(64, "0"))

    async def test_the_fill_is_read_from_the_vault_not_inferred(self):
        # 100 USDC in, and the vault ends up holding 0.05 units: a price of 2,000.
        chain = FakeChain(
            {**answers(position=self.opened()), "balanceOf": lambda w: word("balanceOf", 100_000_000 if not w else 0)},
        )
        fill = await venue(chain).open(
            notional_usd=100.0, stop_price=1900.0, target_price=2200.0,
            deadline=datetime.now(timezone.utc) + timedelta(days=5), min_out=None,
            client_order_id="abc",
        )
        assert fill.qty == pytest.approx(5 * 10**16 / 10**6)
        assert fill.price > 0 and fill.tx_ref == "0xhash"
        # The pool fee is inside that price; charging it again would double-count what
        # the report models once.
        assert fill.fee_usd == 0.0

    async def test_a_simulation_that_reverts_signs_nothing(self):
        chain = FakeChain({**answers(), "_estimate": VenueRejected("BadPrices")})
        signer = FakeSigner()
        with pytest.raises(VenueRejected):
            await venue(chain, signer=signer).open(
                notional_usd=100.0, stop_price=2100.0, target_price=2200.0,
                deadline=datetime.now(timezone.utc) + timedelta(days=5), min_out=None,
                client_order_id="abc",
            )
        assert signer.signed == [] and chain.sent == []

    async def test_a_mined_transaction_with_no_position_is_unknown(self):
        """
        Mined, and the vault disagrees. Nothing here may guess: it becomes
        needs_reconcile and someone asks the chain.
        """
        chain = FakeChain(answers())  # stays flat after the write
        with pytest.raises(VenueUnknown):
            await venue(chain).open(
                notional_usd=100.0, stop_price=1900.0, target_price=2200.0,
                deadline=datetime.now(timezone.utc) + timedelta(days=5), min_out=None,
                client_order_id="abc",
            )

    async def test_nothing_to_spend_is_refused_before_any_call(self):
        chain = FakeChain(answers())
        with pytest.raises(VenueRejected):
            await venue(chain).open(
                notional_usd=0.0, stop_price=1900.0, target_price=None,
                deadline=datetime.now(timezone.utc) + timedelta(days=1), min_out=None,
                client_order_id="abc",
            )
        assert chain.sent == []

    async def test_gas_is_priced_through_the_feed_when_there_is_one(self):
        chain = FakeChain(answers(position=self.opened()))
        without = await venue(chain).open(
            notional_usd=100.0, stop_price=1900.0, target_price=2200.0,
            deadline=datetime.now(timezone.utc) + timedelta(days=5), min_out=None, client_order_id="a",
        )
        assert without.gas_usd == 0.0  # recorded in raw, but not priced

        chain = FakeChain(answers(position=self.opened()))
        with_feed = await venue(chain, eth_feed=ORACLE).open(
            notional_usd=100.0, stop_price=1900.0, target_price=2200.0,
            deadline=datetime.now(timezone.utc) + timedelta(days=5), min_out=None, client_order_id="b",
        )
        # 250,000 gas at 0.1 gwei is 2.5e-5 ETH; at $2,000 that is five cents.
        assert with_feed.gas_usd == pytest.approx(0.05, rel=1e-6)


class TestClose:
    def held(self):
        row = word("position", True, 100_000_000, 5 * 10**16, 200_000_000_000,
                   190_000_000_000, 220_000_000_000, 1_700_000_000, 1_700_500_000)
        flat = word("position", False, 0, 0, 0, 0, 0, 0, 0)
        return lambda writes: flat if writes else row

    @pytest.mark.parametrize(
        "reason,function",
        [("stop", "closeIfStopped"), ("target", "closeIfTargetHit"), ("time", "closeIfExpired"),
         ("opposite", "closeByOperator"), ("flatten", "closeByOperator")],
    )
    async def test_each_reason_calls_the_function_that_verifies_it(self, reason, function):
        chain = FakeChain({**answers(position=self.held()),
                           "balanceOf": lambda w: word("balanceOf", 110_000_000 if w else 0)})
        signer = FakeSigner()
        await venue(chain, signer=signer).close(reason=reason, client_order_id="abc")
        assert signer.signed[0]["data"] == "0x" + selector(function).hex()

    async def test_a_reason_the_vault_cannot_verify_is_refused(self):
        with pytest.raises(VenueRejected):
            await venue(FakeChain(answers())).close(reason="vibes", client_order_id="abc")

    async def test_closing_nothing_is_refused_before_any_write(self):
        chain = FakeChain(answers())
        with pytest.raises(VenueRejected):
            await venue(chain).close(reason="stop", client_order_id="abc")
        assert chain.sent == []

    async def test_what_came_back_is_the_change_in_the_vaults_balance(self):
        chain = FakeChain({**answers(position=self.held()),
                           "balanceOf": lambda w: word("balanceOf", 94_000_000 if w else 0)})
        fill = await venue(chain).close(reason="stop", client_order_id="abc")
        # 0.05 units returned $94, so the exit printed at 1,880.
        assert fill.price == pytest.approx(94.0 / (5 * 10**16 / 10**6))
        assert fill.raw["reason"] == "stop"

    async def test_a_vault_that_still_shows_a_position_afterwards_is_unknown(self):
        row = word("position", True, 100_000_000, 5 * 10**16, 200_000_000_000,
                   190_000_000_000, 220_000_000_000, 1_700_000_000, 1_700_500_000)
        chain = FakeChain({**answers(position=row), "balanceOf": lambda w: word("balanceOf", 0)})
        with pytest.raises(VenueUnknown):
            await venue(chain).close(reason="stop", client_order_id="abc")


class TestBroadcast:
    async def test_a_send_that_was_already_known_still_waits_for_its_receipt(self):
        """
        The node has the transaction. Waiting is right; building a second one is how an
        account spends twice.
        """
        from services.execution.chain import AlreadyBroadcast

        held = word("position", True, 100_000_000, 5 * 10**16, 200_000_000_000,
                    190_000_000_000, 220_000_000_000, 1_700_000_000, 1_700_500_000)
        chain = FakeChain({**answers(position=lambda w: held), "_send": AlreadyBroadcast("already known"),
                           "balanceOf": lambda w: word("balanceOf", 0)})
        fill = await venue(chain).open(
            notional_usd=100.0, stop_price=1900.0, target_price=2200.0,
            deadline=datetime.now(timezone.utc) + timedelta(days=5), min_out=None, client_order_id="abc",
        )
        assert fill.tx_ref == "0xhash"
        assert len(chain.sent) == 1

    async def test_a_receipt_that_never_arrives_is_unknown(self):
        chain = FakeChain({**answers(), "_receipt": VenueUnknown("no receipt for 0xhash yet")})
        with pytest.raises(VenueUnknown) as exc:
            await venue(chain).open(
                notional_usd=100.0, stop_price=1900.0, target_price=2200.0,
                deadline=datetime.now(timezone.utc) + timedelta(days=5), min_out=None, client_order_id="abc",
            )
        # The hash travels with it, which is what makes the timeout answerable.
        assert "0xhash" in str(exc.value)
