"""
The mapping from node failures to "definitely not" and "cannot tell".

This is the most safety-critical translation in the execution path, because the retry
policy is built entirely on it: one of these answers may be retried and the other may
never be. A node that rate-limits, times out, or answers with an internal error says
nothing about whether state changed — and treating any of those as a refusal is how an
account opens two positions.

Driven through a fake httpx transport, so the real client code runs.
"""
import sys
from pathlib import Path
from typing import Any, Dict, List

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from eth_abi import encode as abi_encode
from eth_utils import keccak

from services.execution.abi import VAULT_ERRORS, encode
from services.execution.chain import AlreadyBroadcast, Chain
from services.execution.venue import VenueRejected, VenueUnknown

RPC = "https://node.example/rpc"


def chain_with(responses: List[Any], *, record: Dict[str, Any] | None = None) -> Chain:
    """
    A node that answers from a script. A callable entry may raise, so a transport
    failure can be tested as well as a JSON-RPC error.
    """
    queue = list(responses)
    calls: List[Dict[str, Any]] = []
    if record is not None:
        record["calls"] = calls

    def handler(request: httpx.Request) -> httpx.Response:
        body = __import__("json").loads(request.content)
        calls.append(body)
        answer = queue.pop(0) if queue else {"result": None}
        if callable(answer):
            answer = answer()
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], **answer})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return Chain(RPC, 42161, client=client)


class TestReads:
    async def test_a_call_returns_the_result(self):
        chain = chain_with([{"result": "0x" + "00" * 31 + "2a"}])
        assert (await chain.call("0xvault", encode("closeFloor"))).endswith("2a")

    async def test_a_read_retries_a_flaky_node(self):
        """
        eth_call is idempotent, so a rate limit costs latency and nothing else. This is
        why a public endpoint is usable at all.
        """
        record: Dict[str, Any] = {}
        chain = chain_with(
            [{"error": {"code": -32005, "message": "rate limited"}},
             {"error": {"code": -32005, "message": "rate limited"}},
             {"result": "0x" + "00" * 32}],
            record=record,
        )
        assert await chain.call("0xvault", encode("closeFloor")) is not None
        assert len(record["calls"]) == 3

    async def test_a_read_that_never_succeeds_is_unknown_not_refused(self):
        chain = chain_with([{"error": {"code": -32005, "message": "rate limited"}}] * 4)
        with pytest.raises(VenueUnknown):
            await chain.call("0xvault", encode("closeFloor"))

    async def test_a_revert_is_an_answer_and_is_not_retried(self):
        """
        The node executed it and the contract said no. Retrying would only get the same
        answer, and the reason is worth surfacing in the contract's own words.
        """
        selector = next(k for k, v in VAULT_ERRORS.items() if v == "NotTriggered")
        record: Dict[str, Any] = {}
        chain = chain_with([{"error": {"code": 3, "message": "execution reverted", "data": selector}}], record=record)
        with pytest.raises(VenueRejected) as exc:
            await chain.call("0xvault", encode("closeIfStopped"))
        assert "NotTriggered" in str(exc.value)
        assert len(record["calls"]) == 1

    async def test_a_transport_failure_is_unknown(self):
        def boom():
            raise httpx.ConnectError("no route to host")

        chain = chain_with([boom, boom, boom, boom])
        with pytest.raises(VenueUnknown):
            await chain.nonce("0xme")

    async def test_numbers_come_back_as_integers(self):
        chain = chain_with([{"result": "0x10"}, {"result": "0x3b9aca00"}])
        assert await chain.nonce("0xme") == 16
        assert await chain.gas_price() == 1_000_000_000


class TestEstimate:
    async def test_the_estimate_is_the_simulation(self):
        """
        A revert here is a definite refusal learned *before* anything is broadcast,
        which is how most failures become VenueRejected rather than VenueUnknown.
        """
        payload = keccak(text="Error(string)")[:4] + abi_encode(["string"], ["Too little received"])
        chain = chain_with([{"error": {"code": 3, "message": "execution reverted", "data": "0x" + payload.hex()}}])
        with pytest.raises(VenueRejected) as exc:
            await chain.estimate_gas(frm="0xme", to="0xvault", data="0x00")
        assert "Too little received" in str(exc.value)

    async def test_an_estimate_returns_gas(self):
        chain = chain_with([{"result": "0x5208"}])
        assert await chain.estimate_gas(frm="0xme", to="0xvault", data="0x00") == 21_000


class TestSend:
    async def test_a_send_is_never_retried(self):
        record: Dict[str, Any] = {}
        chain = chain_with([{"error": {"code": -32000, "message": "timeout"}}], record=record)
        with pytest.raises(VenueUnknown):
            await chain.send_raw("0xdeadbeef")
        assert len(record["calls"]) == 1, "a retried send is how an account spends twice"

    async def test_already_known_is_not_a_failure_to_broadcast(self):
        """
        The node has it, or has had it. Building a second transaction because of this
        message would be exactly the wrong response.
        """
        chain = chain_with([{"error": {"code": -32000, "message": "already known"}}])
        with pytest.raises(AlreadyBroadcast):
            await chain.send_raw("0xdeadbeef")

    async def test_a_nonce_that_is_too_low_says_the_same_thing(self):
        chain = chain_with([{"error": {"code": -32000, "message": "nonce too low"}}])
        with pytest.raises(AlreadyBroadcast):
            await chain.send_raw("0xdeadbeef")


class TestReceipt:
    async def test_a_successful_receipt_comes_back_parsed(self):
        chain = chain_with([{"result": {"status": "0x1", "blockNumber": "0x64", "gasUsed": "0x7a120"}}])
        receipt = await chain.wait_for_receipt("0xhash", attempts=1, interval=0)
        assert receipt.ok and receipt.block_number == 100 and receipt.gas_used == 500_000

    async def test_a_reverted_transaction_is_a_refusal(self):
        chain = chain_with([{"result": {"status": "0x0", "blockNumber": "0x64", "gasUsed": "0x1"}}])
        with pytest.raises(VenueRejected):
            await chain.wait_for_receipt("0xhash", attempts=1, interval=0)

    async def test_no_receipt_yet_is_unknown_and_carries_the_hash(self):
        """
        The hash is what makes a timeout recoverable: we signed locally, so it exists
        before the broadcast does, and reconciliation has a definite question to ask.
        """
        chain = chain_with([{"result": None}, {"result": None}])
        with pytest.raises(VenueUnknown) as exc:
            await chain.wait_for_receipt("0xabc123", attempts=2, interval=0)
        assert "0xabc123" in str(exc.value)


PRIMARY = "https://primary.example/rpc"
FALLBACK = "https://fallback.example/rpc"


def two_nodes(primary: List[Any], fallback: List[Any]):
    """A primary and a fallback node, each answering from its own script."""
    seen: List[str] = []
    queues = {PRIMARY: list(primary), FALLBACK: list(fallback)}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        seen.append(url)
        body = __import__("json").loads(request.content)
        answer = queues[url].pop(0) if queues[url] else {"result": None}
        if callable(answer):
            answer = answer()
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], **answer})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return Chain(PRIMARY, 4663, client=client, fallback_url=FALLBACK), seen


def _down():
    raise httpx.ConnectError("primary unreachable")


class TestFallback:
    async def test_a_read_the_primary_cannot_answer_is_asked_of_the_fallback(self):
        chain, seen = two_nodes([_down, _down, _down], [{"result": "0x2a"}])
        assert await chain.gas_price() == 42
        assert seen.count(FALLBACK) == 1

    async def test_a_healthy_primary_never_touches_the_fallback(self):
        chain, seen = two_nodes([{"result": "0x2a"}], [])
        assert await chain.gas_price() == 42
        assert FALLBACK not in seen

    async def test_a_revert_is_an_answer_and_is_not_re_asked(self):
        data = next(k for k, v in VAULT_ERRORS.items() if v == "NotTriggered")
        chain, seen = two_nodes([{"error": {"message": "execution reverted", "data": data}}], [])
        with pytest.raises(VenueRejected):
            await chain.call("0x" + "11" * 20, "0x")
        assert FALLBACK not in seen

    async def test_a_send_the_primary_could_not_confirm_goes_to_the_fallback_once(self):
        chain, seen = two_nodes([{"error": {"message": "rate limited"}}], [{"result": "0x" + "ab" * 32}])
        assert await chain.send_raw("0xdead") == "0x" + "ab" * 32
        assert seen == [PRIMARY, FALLBACK]

    async def test_a_send_the_fallback_already_has_is_already_broadcast_not_a_new_trade(self):
        chain, _ = two_nodes([{"error": {"message": "timeout"}}], [{"error": {"message": "already known"}}])
        with pytest.raises(AlreadyBroadcast):
            await chain.send_raw("0xdead")

    async def test_already_known_on_the_primary_is_not_offered_to_the_fallback(self):
        chain, seen = two_nodes([{"error": {"message": "nonce too low"}}], [])
        with pytest.raises(AlreadyBroadcast):
            await chain.send_raw("0xdead")
        assert FALLBACK not in seen

    async def test_both_nodes_down_is_still_unknown(self):
        chain, _ = two_nodes([{"error": {"message": "down"}}], [{"error": {"message": "also down"}}])
        with pytest.raises(VenueUnknown, match="fallback"):
            await chain.send_raw("0xdead")

    def test_the_same_url_twice_is_no_fallback(self):
        assert Chain(PRIMARY, 4663, fallback_url=PRIMARY).fallback_url is None
