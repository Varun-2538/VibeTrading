"""
Who signs the executor's transactions.

An interface with one implementation, on purpose. The key that opens and closes
positions is the one piece of material we hold, and where it lives has to be a
swappable decision rather than a fact spread through the code: an env-var key is fine
on a testnet where the funds are worthless, and it is not what should sign against
mainnet. A KMS signer implements this same protocol - the key never leaves the
service, and `sign` becomes a remote call - and nothing else has to change.

What limits the damage either way is the vault, not this file. The key can swap
inside a contract the owner controls, within caps they set, and there is no code path
by which it can withdraw. That is the part of the design that makes a leaked
operator key survivable; this part just decides how hard it is to leak.
"""
from dataclasses import dataclass
from typing import Any, Dict, Optional, Protocol, runtime_checkable

from eth_account import Account
from eth_utils import keccak, to_checksum_address


@dataclass(frozen=True)
class SignedTransaction:
    """
    A transaction and the hash it will have.

    The hash comes back **before** anything is broadcast, which is what lets a send
    that times out be asked about instead of guessed at.
    """

    raw: str
    tx_hash: str
    nonce: int


@runtime_checkable
class Signer(Protocol):
    @property
    def address(self) -> str:
        ...

    async def sign(self, transaction: Dict[str, Any]) -> SignedTransaction:
        ...


class LocalSigner:
    """
    A key in the process's environment.

    For a testnet, and for a mainnet vault capped at a few hundred dollars while the
    contract is unaudited. Anyone with access to the machine can read it, so the
    honest way to describe the protection is: the vault, not this.

    The key is never logged, never returned, and never put in an error message - the
    address is the only thing this object will say about itself.
    """

    def __init__(self, private_key: str):
        key = private_key.strip()
        if not key:
            raise ValueError("no signing key configured")
        if not key.startswith("0x"):
            key = "0x" + key
        self._account = Account.from_key(key)

    @property
    def address(self) -> str:
        return to_checksum_address(self._account.address)

    async def sign(self, transaction: Dict[str, Any]) -> SignedTransaction:
        signed = self._account.sign_transaction(transaction)
        raw = signed.raw_transaction if hasattr(signed, "raw_transaction") else signed.rawTransaction
        return SignedTransaction(
            raw="0x" + raw.hex() if not raw.hex().startswith("0x") else raw.hex(),
            tx_hash="0x" + keccak(raw).hex(),
            nonce=int(transaction["nonce"]),
        )

    def __repr__(self) -> str:  # pragma: no cover - defensive, so a log cannot leak
        return f"LocalSigner({self.address})"


def signer_from_settings() -> Optional[Signer]:
    """
    The signer this deployment has, or None.

    None is a normal state: shadow mode needs no key at all, and an executor with no
    key should idle rather than fail to start - the alternative is a container that
    crash-loops on a machine that was only ever meant to run shadow.
    """
    from config import settings

    key = (getattr(settings, "executor_private_key", "") or "").strip()
    if not key:
        return None
    return LocalSigner(key)
