"""
The venue that is a vault on Arbitrum.

Every write here is the same five steps, in this order, and the order is the safety
property:

1. ask the vault what its own floor is, so our minimum-out cannot disagree with the
   one it will enforce;
2. simulate with `eth_estimateGas` - a revert at this point is a definite refusal,
   and it is how most failures become VenueRejected before anything is broadcast;
3. sign locally, which yields the transaction hash *before* it exists on any node;
4. broadcast once, never retried;
5. wait for the receipt, and read the vault to see what actually happened.

Step 3 is what makes a public RPC workable. A send that times out is not a dead end:
the hash is already known, so the question "did it happen" has a definite answer
available to reconciliation instead of a guess.

Amounts are read, not assumed. The fill price comes from the vault's own position
after the swap - and on the way out, from the change in its stablecoin balance -
because what a swap returned is a fact about the pool, and inferring it from a quote
would put a number in the audit trail that nothing on chain agrees with.
"""
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from services.execution.abi import decode, encode
from services.execution.chain import AlreadyBroadcast, Chain
from services.execution.signer import Signer
from services.execution.venue import Fill, Quote, VenuePosition, VenueRejected, VenueUnknown

ORACLE_SCALE = 10**8  # Chainlink, 8 decimals
GAS_LIMIT_PADDING = 130  # percent of the estimate, for a router whose path may vary

CLOSE_FUNCTIONS = {
    "stop": "closeIfStopped",
    "target": "closeIfTargetHit",
    "time": "closeIfExpired",
    "opposite": "closeByOperator",
    "flatten": "closeByOperator",
}


class VaultVenue:
    """
    One vault, one market. Stateless apart from decimals, which are immutable on the
    contracts and read once.
    """

    def __init__(
        self,
        *,
        chain: Chain,
        signer: Signer,
        market: str,
        vault: Optional[str] = None,
        owner: Optional[str] = None,
        asset: Optional[str] = None,
        factory: Optional[str] = None,
        eth_usd_feed: Optional[str] = None,
        confirm: bool = True,
    ):
        self.chain = chain
        self.signer = signer
        self.market = market
        self.market_asset = asset
        self.owner = owner
        self.factory = factory
        self.eth_usd_feed = eth_usd_feed
        self.confirm = confirm
        self._vault = vault
        self._cache: Dict[str, Any] = {}

    async def target(self) -> str:
        """
        The vault this is trading in.

        Resolved from the factory rather than stored on the policy, because the
        factory is the one place that knows which contract belongs to an owner - and a
        stale address in our database would be a transaction sent to the wrong
        contract. Looked up once and cached; the mapping cannot change.
        """
        if self._vault:
            return self._vault
        if not (self.factory and self.owner and self.market_asset):
            raise VenueRejected("no vault address, and nothing to look one up with")
        found = decode(
            "vaultOf", await self.chain.call(self.factory, encode("vaultOf", self.owner, self.market_asset))
        )[0]
        if int(found, 16) == 0:
            raise VenueRejected("this wallet has no vault for that market yet")
        self._vault = found
        return found

    # --- immutable facts, read once -------------------------------------------

    async def _addresses(self) -> Dict[str, Any]:
        if "stable" not in self._cache:
            vault = await self.target()
            self._cache["stable"] = decode("stable", await self.chain.call(vault, encode("stable")))[0]
            self._cache["asset"] = decode("asset", await self.chain.call(vault, encode("asset")))[0]
            self._cache["oracle"] = decode("oracle", await self.chain.call(vault, encode("oracle")))[0]
            self._cache["stable_decimals"] = decode(
                "decimals", await self.chain.call(self._cache["stable"], encode("decimals"))
            )[0]
            self._cache["asset_decimals"] = decode(
                "decimals", await self.chain.call(self._cache["asset"], encode("decimals"))
            )[0]
        return self._cache

    # --- reads -----------------------------------------------------------------

    async def quote(self) -> Quote:
        """
        The oracle's price, not the pool's.

        Deliberately: it is the price the vault will check a stop against, so a
        monitor that triggered on anything else would ask for exits the contract
        refuses.
        """
        cache = await self._addresses()
        answer = decode("latestRoundData", await self.chain.call(cache["oracle"], encode("latestRoundData")))
        price = int(answer[1])
        if price <= 0:
            raise VenueRejected("the oracle has no usable price")
        return Quote(price=price / ORACLE_SCALE, at=datetime.fromtimestamp(int(answer[3]), tz=timezone.utc))

    async def balance(self) -> float:
        cache = await self._addresses()
        raw = decode("balanceOf", await self.chain.call(cache["stable"], encode("balanceOf", await self.target())))[0]
        return int(raw) / 10 ** int(cache["stable_decimals"])

    async def position(self) -> VenuePosition:
        cache = await self._addresses()
        row = decode("position", await self.chain.call(await self.target(), encode("position")))
        if not row[0]:
            return VenuePosition(open=False)
        return VenuePosition(
            open=True,
            qty=int(row[2]) / 10 ** int(cache["asset_decimals"]),
            entry_price=int(row[3]) / ORACLE_SCALE,
            stop_price=int(row[4]) / ORACLE_SCALE,
            target_price=(int(row[5]) / ORACLE_SCALE) or None,
            deadline=datetime.fromtimestamp(int(row[7]), tz=timezone.utc) if row[7] else None,
        )

    # --- writes ----------------------------------------------------------------

    async def open(
        self,
        *,
        notional_usd: float,
        stop_price: float,
        target_price: Optional[float],
        deadline: datetime,
        min_out: Optional[float],
        client_order_id: str,
    ) -> Fill:
        cache = await self._addresses()
        amount_in = int(round(notional_usd * 10 ** int(cache["stable_decimals"])))
        if amount_in <= 0:
            raise VenueRejected("nothing to spend")

        # The vault's own floor, so our minimum cannot be looser than the one it
        # enforces - and cannot be tighter either, which would refuse fills the owner
        # already agreed to.
        floor = decode("openFloor", await self.chain.call(await self.target(), encode("openFloor", amount_in)))[0]

        before = await self.balance()
        data = encode(
            "openPosition",
            amount_in,
            int(round(stop_price * ORACLE_SCALE)),
            int(round((target_price or 0) * ORACLE_SCALE)),
            int(deadline.timestamp()),
            int(floor),
        )
        receipt = await self._send(data, client_order_id)

        # What the swap actually bought, from the vault rather than from a guess.
        after = await self.position()
        if not after.open:
            raise VenueUnknown("the transaction was mined but the vault shows no position")
        spent = before - await self.balance()
        price = (spent / after.qty) if after.qty else 0.0
        return Fill(
            venue_fill_id=receipt["tx_hash"],
            price=price,
            qty=after.qty,
            # The pool fee is already inside that price; charging it again would
            # double-count what the report models once.
            fee_usd=0.0,
            gas_usd=await self._gas_usd(receipt),
            at=datetime.now(timezone.utc),
            tx_ref=receipt["tx_hash"],
            raw={"receipt": receipt["summary"], "amount_in": amount_in, "min_out": int(floor),
                 "client_order_id": client_order_id},
        )

    async def close(self, *, reason: str, client_order_id: str) -> Fill:
        function = CLOSE_FUNCTIONS.get(reason)
        if function is None:
            raise VenueRejected(f"no way to close for {reason!r}")
        held = await self.position()
        if not held.open:
            raise VenueRejected("nothing open to close")

        before = await self.balance()
        receipt = await self._send(encode(function), client_order_id)
        received = await self.balance() - before
        still = await self.position()
        if still.open:
            raise VenueUnknown("the transaction was mined but the vault still shows a position")
        return Fill(
            venue_fill_id=receipt["tx_hash"],
            price=(received / held.qty) if held.qty else 0.0,
            qty=held.qty,
            fee_usd=0.0,
            gas_usd=await self._gas_usd(receipt),
            at=datetime.now(timezone.utc),
            tx_ref=receipt["tx_hash"],
            raw={"receipt": receipt["summary"], "reason": reason, "received": received,
                 "client_order_id": client_order_id},
        )

    # --- the five steps --------------------------------------------------------

    async def _send(self, data: str, client_order_id: str) -> Dict[str, Any]:
        """
        Simulate, sign, broadcast once, wait.

        The estimate is the simulation: a revert here is a definite refusal and the
        transaction is never built, which is how a stop the oracle disagrees with
        costs nothing but a read.
        """
        vault = await self.target()
        gas = await self.chain.estimate_gas(frm=self.signer.address, to=vault, data=data)
        nonce = await self.chain.nonce(self.signer.address)
        gas_price = await self.chain.gas_price()

        signed = await self.signer.sign(
            {
                "to": vault,
                "data": data,
                "gas": gas * GAS_LIMIT_PADDING // 100,
                "gasPrice": gas_price,
                "nonce": nonce,
                "value": 0,
                "chainId": self.chain.chain_id,
            }
        )
        try:
            await self.chain.send_raw(signed.raw)
        except AlreadyBroadcast:
            # The node has it already. Waiting is right; sending again is not.
            pass
        if not self.confirm:
            return {"tx_hash": signed.tx_hash, "summary": {"broadcast_only": True}}

        receipt = await self.chain.wait_for_receipt(signed.tx_hash)
        return {
            "tx_hash": signed.tx_hash,
            "gas_used": receipt.gas_used,
            "gas_price": gas_price,
            "summary": {"block": receipt.block_number, "gas_used": receipt.gas_used,
                        "gas_price": gas_price, "status": receipt.status},
        }

    async def _gas_usd(self, receipt: Dict[str, Any]) -> float:
        """
        What the transaction cost, in dollars.

        Priced through the ETH/USD feed when one is configured. Without it the wei are
        still recorded on the order, but gas reads as zero - and an under-reported cost
        flatters a strategy, so the feed is configured rather than optional in
        anything that matters.
        """
        used, price = receipt.get("gas_used"), receipt.get("gas_price")
        if not used or not price or not self.eth_usd_feed:
            return 0.0
        answer = decode("latestRoundData", await self.chain.call(self.eth_usd_feed, encode("latestRoundData")))
        eth_usd = int(answer[1]) / ORACLE_SCALE
        return (used * price / 10**18) * eth_usd
