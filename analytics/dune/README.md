# Dune dashboard: VibeTrading vaults on Robinhood Chain

Three DuneSQL queries over `robinhood.logs`. They read raw event logs by topic, so
they work without submitting the contract ABI for decoding.

| File | Shows | Visualisation |
|---|---|---|
| `03_summary.sql` | vaults deployed, USDG deposited, positions opened and closed, how many were closed by a third party, bounties paid | one **Counter** per column |
| `02_trades.sql` | every position: entry, stop, target, exit, P&L, and **who closed it** (our executor, the owner, or a stranger paid the bounty) | **Table** |
| `01_vaults.sql` | every vault: owner, market (ETH or a Stock Token), disclosure hash | **Table** |

The offsets were checked against the live logs of the first mainnet trade: a 2 USDG
NVDA position opened at $235.00 and closed on expiry by a third party for a 1 USDG
bounty.

## Building it

1. dune.com → **Create** → **New query**. Engine: DuneSQL (the default).
2. Paste a file, **Run**, **Save** with its title.
3. Under the results, **New visualisation** as in the table above.
4. **Create** → **New dashboard** → **Add visualisation**, and add the three.
5. Share the dashboard link.

Contract addresses are the Robinhood Chain factory
`0x04C96936670c38982D1e7eF23caDd84d6891c818`; event topics are `keccak256` of the
signatures in `contracts/src/TradingVault.sol` and `VaultFactory.sol`.
