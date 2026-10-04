# Vaults

One contract per user. It holds their dollars, it can swap into one whitelisted
asset and back, and it can do nothing else.

| Chain | Dollar | Markets | Pool tier |
|---|---|---|---|
| Arbitrum One (42161) | USDC | WETH, WBTC | 0.05% |
| Robinhood Chain (4663) | USDG (Paxos) | WETH | 0.01% |

The same contracts on both; only the addresses differ, and those live in
`src/Addresses.sol`. Robinhood Chain is ETH only for now: Stock Tokens have pools and
Chainlink feeds there, but those feeds follow US market hours, and a 26-hour
staleness rule would freeze every stock vault from Saturday to Monday - opens and
exits alike. That needs its own rule before it ships.

We run the bot, so we hold an operator key. The whole design exists to make that key
survivable: it can open a position and it can close one, and there is no code path
by which it can move money out, change where the stop is, raise a cap, or point the
vault at a different router.

## What the operator can do

```
openPosition(amountIn, stopPrice, targetPrice, deadline, minOut)
closeByOperator()      // an opposing signal, or a kill switch reaching us
```

Nothing else. `openPosition` writes the stop, the target and the deadline into
storage, and **no function anywhere changes them afterwards** — not for us, not for
the owner. A bot cannot give a losing position "a little more room".

## What the owner can always do

```
deposit(amount)                        // up to the factory's hard TVL cap
withdraw(token, amount, to)            // any time, position open or not
setOperator(who, expiry) / revokeOperator()
setCaps(maxNotional, tradesPerDay, slippageBps, bounty)
closeByOwner()
```

Revoking is unilateral and immediate. We cannot block it, delay it, or notice it
first.

## Exits that do not depend on us

A contract cannot notice a price — EVM code runs only when a transaction calls it.
So the vault *verifies* conditions and something outside *pushes the button*:

```
closeIfStopped()     // reverts unless the oracle price is at or below the stop
closeIfTargetHit()   // reverts unless it is at or above the target
closeIfExpired()     // reverts before the deadline
```

All three are **permissionless** and pay a small flat bounty from the vault to
whoever calls them — unless the caller is us or the owner, because paying ourselves
out of their vault for work we said we would do is a fee by another name.

Our executor normally calls them within seconds. If it is down, a stranger has a
profit motive to do it instead. That is the same mechanism that makes lending
liquidations reliable without trusting any single operator, and it is why the risk
page can stop saying that a stop depends on our uptime.

**Oracle authorises, minimum-out protects.** The Chainlink feed decides whether an
exit is allowed; the minimum the vault derives from that same price is what stops
the caller routing the swap through a manipulated pool and keeping the difference.
The vault publishes `openFloor(amountIn)` and `closeFloor()` so the executor asks
the vault what the floor is rather than computing its own and disagreeing.

A feed that has stopped updating authorises nothing, in either direction:
`MAX_ORACLE_AGE` is 26 hours, which is the daily heartbeat plus slack. Tighter than
that would make exits impossible in a quiet market, which is worse than the risk it
removes.

## The risk ladder

This contract holds real money, and a bug here is not like a bug in the backend —
that costs latency, this costs the money.

1. **Mainnet forks.** Everything, end to end, against the real router, the real
   pool and the real feed on each chain, including a third party pushing an exit
   and collecting the bounty. This replaced a Sepolia deployment: testnet pools are
   thin and Robinhood Chain's testnet has no Chainlink feeds at all, so a fork of
   mainnet is the more honest rehearsal.
2. **Mainnet with `TVL_CAP = 500e6`** — five hundred dollars a vault, hardcoded in
   the factory. Nobody, including us, can raise it without deploying a new factory.
3. **An external audit.**
4. Only then, a higher cap.

## Running the tests

```
forge build
forge test                                  # 28 offline tests, mocks only
ARBITRUM_RPC_URL=https://arb1.arbitrum.io/rpc ROBINHOOD_RPC_URL=https://rpc.mainnet.chain.robinhood.com   forge test --match-path test/Fork.t.sol -vv   # 4 per chain
```

The fork tests build the factory from `Deploy.config(block.chainid)`, the function
the deploy script itself uses, so what passes is what gets deployed. They are the
only ones that can tell whether the addresses in
`src/Addresses.sol` are the contracts we believe they are — everything else runs
against mocks that agree with us by construction. **Run it before deploying.**

## Deploying

```
forge script script/Deploy.s.sol --rpc-url $RPC --private-key $KEY --broadcast
```

The script reads the chain off the RPC and refuses one it does not know, so the
markets cannot be the other chain's by mistake.

That deploys the *factory*. Vaults are deployed by their owners from the app, so the
owner of a vault is always the wallet that asked for it.

## Files

| File | |
|---|---|
| `src/TradingVault.sol` | the vault: one asset, one position at a time |
| `src/VaultFactory.sol` | one vault per (owner, asset); fixes the router, feeds and cap |
| `src/Addresses.sol` | every mainnet literal, per chain, asserted by the fork tests |
| `script/Deploy.s.sol` | the factory, with markets chosen by chain id |
| `src/interfaces/` | four-line interfaces instead of a dependency |
| `test/TradingVault.t.sol` | mostly refusals, because that is what the vault is for |
| `test/Fork.t.sol` | the addresses are real, and a round trip works; skipped without an RPC URL |

No submodules and no libraries, on purpose. This contract is meant to be read end
to end in one sitting.
