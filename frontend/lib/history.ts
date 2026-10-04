/**
 * Trade history, read from the owner's vaults on chain.
 *
 * Every open and every close is an event the vault emitted, so the history is the
 * vault's own log rather than a record we keep: each row links to the transaction
 * that did it, and a close names who sent it - you, our executor, or a stranger the
 * vault paid a bounty to.
 */
import { useEffect, useState } from "react"
import { parseAbi, parseEventLogs, type Address, type Hash } from "viem"
import { getPublicClient } from "wagmi/actions"

import { DEPLOYED_FACTORY } from "@/lib/positions"
import { FACTORY_ABI, VAULT_ABI, VAULT_MARKETS, type VaultMarket } from "@/lib/vault"
import { wagmiConfig } from "@/lib/wallet"

const ZERO = "0x0000000000000000000000000000000000000000"
const REFRESH_MS = 30_000
// Robinhood Chain's RPC allows ten million blocks a query by address alone, but only
// a hundred thousand once topics are filtered - so ask by address and decode here.
const LOOKBACK_BLOCKS = BigInt(9_990_000)

const EVENTS = parseAbi([
  "event Opened(uint256 spent, uint256 qty, uint256 entryPrice, uint256 stopPrice, uint256 targetPrice, uint64 deadline)",
  "event Closed(string reason, uint256 qty, uint256 received, uint256 price, address closedBy, uint256 bountyPaid)",
])

export const EXPLORER: Record<number, string> = {
  4663: "https://robinhoodchain.blockscout.com",
  42161: "https://arbiscan.io",
}

export type Closer = "you" | "executor" | "stranger"

export interface HistoryTrade {
  market: string
  label: string
  chainId: number
  chainName: string
  stable: string
  vault: Address
  openTx: Hash
  openedAt: number | null // unix seconds
  spentUsd: number
  entry: number
  stop: number
  target: number | null
  close: {
    tx: Hash
    at: number | null
    reason: string
    price: number
    receivedUsd: number
    bountyUsd: number
    by: Address
    closer: Closer
  } | null
}

async function readVaultHistory(m: VaultMarket, owner: Address): Promise<HistoryTrade[]> {
  const factory = DEPLOYED_FACTORY[m.chainId]
  const client = getPublicClient(wagmiConfig, { chainId: m.chainId as 42161 | 4663 })
  if (!factory || !client) return []
  const vault = (await client.readContract({
    address: factory,
    abi: FACTORY_ABI,
    functionName: "vaultOf",
    args: [owner, m.asset],
  })) as Address
  if (vault === ZERO) return []

  const latest = await client.getBlockNumber()
  const fromBlock = latest > LOOKBACK_BLOCKS ? latest - LOOKBACK_BLOCKS : BigInt(0)
  const [raw, operator] = await Promise.all([
    client.getLogs({ address: vault, fromBlock, toBlock: latest }),
    client.readContract({ address: vault, abi: VAULT_ABI, functionName: "operator" }) as Promise<Address>,
  ])

  const logs = parseEventLogs({ abi: EVENTS, logs: raw })

  const times = new Map<bigint, number>()
  await Promise.all(
    [...new Set(logs.map((l) => l.blockNumber))].map(async (n) => {
      if (n === null) return
      const block = await client.getBlock({ blockNumber: n })
      times.set(n, Number(block.timestamp))
    }),
  )
  const at = (n: bigint | null) => (n === null ? null : (times.get(n) ?? null))

  const trades: HistoryTrade[] = []
  for (const log of logs) {
    if (log.eventName === "Opened") {
      const a = log.args
      trades.push({
        market: m.market,
        label: m.label,
        chainId: m.chainId,
        chainName: m.chainName,
        stable: m.stable,
        vault,
        openTx: log.transactionHash as Hash,
        openedAt: at(log.blockNumber),
        spentUsd: Number(a.spent ?? BigInt(0)) / 1e6,
        entry: Number(a.entryPrice ?? BigInt(0)) / 1e8,
        stop: Number(a.stopPrice ?? BigInt(0)) / 1e8,
        target: a.targetPrice ? Number(a.targetPrice) / 1e8 : null,
        close: null,
      })
    } else if (log.eventName === "Closed") {
      const open = [...trades].reverse().find((t) => t.close === null)
      if (!open) continue // closed a position opened before the lookback window
      const a = log.args
      const by = (a.closedBy ?? ZERO) as Address
      open.close = {
        tx: log.transactionHash as Hash,
        at: at(log.blockNumber),
        reason: a.reason ?? "",
        price: Number(a.price ?? BigInt(0)) / 1e8,
        receivedUsd: Number(a.received ?? BigInt(0)) / 1e6,
        bountyUsd: Number(a.bountyPaid ?? BigInt(0)) / 1e6,
        by,
        closer:
          by.toLowerCase() === owner.toLowerCase()
            ? "you"
            : by.toLowerCase() === operator.toLowerCase()
              ? "executor"
              : "stranger",
      }
    }
  }
  return trades
}

/** Every trade in the owner's vaults, newest first, refreshed every 30 seconds. */
export function useTradeHistory(owner: string | undefined | null): {
  trades: HistoryTrade[]
  loading: boolean
} {
  const [trades, setTrades] = useState<HistoryTrade[]>([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!owner) {
      setTrades([])
      return
    }
    let alive = true
    const load = async () => {
      setLoading(true)
      const found: HistoryTrade[] = []
      await Promise.all(
        VAULT_MARKETS.map(async (m) => {
          try {
            found.push(...(await readVaultHistory(m, owner as Address)))
          } catch {
            // A chain that does not answer this round is asked again on the next.
          }
        }),
      )
      if (!alive) return
      setTrades(found.sort((a, b) => (b.openedAt ?? 0) - (a.openedAt ?? 0)))
      setLoading(false)
    }
    void load()
    const id = window.setInterval(load, REFRESH_MS)
    return () => {
      alive = false
      window.clearInterval(id)
    }
  }, [owner])

  return { trades, loading }
}
