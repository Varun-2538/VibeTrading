"""
A JSON-RPC client that knows the difference between "no" and "I don't know".

That distinction is the whole reason this is hand-written rather than delegated to a
library. Everything the executor does with a chain has to end in exactly one of two
answers - it definitely did not happen, or we cannot tell - and the mapping from HTTP
and JSON-RPC failures to those two answers is the most safety-critical code in the
execution path.

Reads retry freely: `eth_call` and a balance are idempotent, so a flaky node costs
latency and nothing else. Sends retry **never**.

The trick that makes a public node usable for sends: we sign locally, so the
transaction hash is known *before* it is broadcast. A send that times out is
therefore not a dead end - the hash can be asked about until the answer is definite.
Without that, every timeout on a rate-limited node would strand an intent.
"""
import asyncio
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx

from services.execution.abi import revert_reason
from services.execution.venue import VenueRejected, VenueUnknown

READ_ATTEMPTS = 3
READ_BACKOFF_SECONDS = 0.4
RECEIPT_ATTEMPTS = 20
RECEIPT_INTERVAL_SECONDS = 1.5
TIMEOUT_SECONDS = 20.0


@dataclass(frozen=True)
class Receipt:
    tx_hash: str
    status: int
    block_number: int
    gas_used: int
    raw: Dict[str, Any]

    @property
    def ok(self) -> bool:
        return self.status == 1


class Chain:
    """
    One node, one chain id. Holds its own client so connection reuse is not left to
    chance - a fresh TLS handshake per call was measurably expensive in the candle
    service and would be worse here, where latency is the difference between being
    first to a stop and not.
    """

    def __init__(self, rpc_url: str, chain_id: int, *, client: Optional[httpx.AsyncClient] = None):
        self.rpc_url = rpc_url
        self.chain_id = chain_id
        self._client = client
        self._id = 0

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=TIMEOUT_SECONDS)
        return self._client

    async def _rpc(self, method: str, params: List[Any], *, retries: int = 0) -> Any:
        """
        One call. `retries` is only ever non-zero for reads, and the caller decides -
        this function will not retry something a caller did not say is idempotent.
        """
        self._id += 1
        payload = {"jsonrpc": "2.0", "id": self._id, "method": method, "params": params}
        last: Optional[Exception] = None
        for attempt in range(retries + 1):
            try:
                response = await self._http().post(self.rpc_url, json=payload)
                response.raise_for_status()
                body = response.json()
            except Exception as exc:  # noqa: BLE001 - mapped by the caller's semantics
                last = exc
                if attempt < retries:
                    await asyncio.sleep(READ_BACKOFF_SECONDS * (attempt + 1))
                    continue
                raise VenueUnknown(f"{method}: {exc}") from exc

            error = body.get("error")
            if error is None:
                return body.get("result")

            message = str(error.get("message", "rpc error"))
            data = error.get("data")
            # A revert is an answer: the node executed it and the contract said no.
            if "revert" in message.lower() or (isinstance(data, str) and data.startswith("0x")):
                raise VenueRejected(f"{method}: {revert_reason(data) if data else message}")
            if attempt < retries:
                await asyncio.sleep(READ_BACKOFF_SECONDS * (attempt + 1))
                last = VenueUnknown(message)
                continue
            # Everything else from a node - rate limits, "already known", internal
            # errors - says nothing about whether state changed.
            raise VenueUnknown(f"{method}: {message}")
        raise VenueUnknown(f"{method}: {last}")

    # --- reads, freely retried -------------------------------------------------

    async def call(self, to: str, data: str) -> str:
        return await self._rpc("eth_call", [{"to": to, "data": data}, "latest"], retries=READ_ATTEMPTS - 1)

    async def nonce(self, address: str) -> int:
        result = await self._rpc("eth_getTransactionCount", [address, "pending"], retries=READ_ATTEMPTS - 1)
        return int(result, 16)

    async def gas_price(self) -> int:
        result = await self._rpc("eth_gasPrice", [], retries=READ_ATTEMPTS - 1)
        return int(result, 16)

    async def estimate_gas(self, *, frm: str, to: str, data: str) -> int:
        """
        Also the pre-flight simulation. A revert here is a definite refusal, which is
        exactly what we want to learn *before* anything is broadcast - it is how most
        failures become VenueRejected rather than VenueUnknown.
        """
        result = await self._rpc(
            "eth_estimateGas", [{"from": frm, "to": to, "data": data}], retries=READ_ATTEMPTS - 1
        )
        return int(result, 16)

    async def transaction(self, tx_hash: str) -> Optional[Dict[str, Any]]:
        return await self._rpc("eth_getTransactionByHash", [tx_hash], retries=READ_ATTEMPTS - 1)

    async def receipt(self, tx_hash: str) -> Optional[Receipt]:
        raw = await self._rpc("eth_getTransactionReceipt", [tx_hash], retries=READ_ATTEMPTS - 1)
        if raw is None:
            return None
        return Receipt(
            tx_hash=tx_hash,
            status=int(raw.get("status", "0x0"), 16),
            block_number=int(raw.get("blockNumber", "0x0"), 16),
            gas_used=int(raw.get("gasUsed", "0x0"), 16),
            raw=raw,
        )

    # --- the one write ---------------------------------------------------------

    async def send_raw(self, signed_hex: str) -> str:
        """
        Broadcast, once, with no retry of any kind.

        "already known" and "nonce too low" are not failures to broadcast - they mean
        the node has it, or has had it. Treated as success so a duplicate broadcast
        cannot be mistaken for a reason to build a second transaction.
        """
        try:
            return await self._rpc("eth_sendRawTransaction", [signed_hex])
        except VenueUnknown as exc:
            text = str(exc).lower()
            if "already known" in text or "already imported" in text or "nonce too low" in text:
                raise AlreadyBroadcast(str(exc)) from exc
            raise

    async def wait_for_receipt(
        self, tx_hash: str, *, attempts: int = RECEIPT_ATTEMPTS, interval: float = RECEIPT_INTERVAL_SECONDS
    ) -> Receipt:
        """
        Poll until the chain answers, then say what it answered.

        A timeout here raises VenueUnknown carrying the hash, which is the whole point
        of signing locally: the hash outlives the timeout, so reconciliation has a
        definite question to ask rather than a guess to make.
        """
        for _ in range(attempts):
            got = await self.receipt(tx_hash)
            if got is not None:
                if not got.ok:
                    # Mined and reverted: definite, and safe to retry as a decision -
                    # though the caller usually should not, since the same calldata
                    # would revert again.
                    raise VenueRejected(f"transaction {tx_hash} reverted on chain")
                return got
            await asyncio.sleep(interval)
        raise VenueUnknown(f"no receipt for {tx_hash} yet")


class AlreadyBroadcast(Exception):
    """The node has this transaction already; wait for it rather than sending again."""
