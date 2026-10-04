/**
 * Open positions, read from the owner's vaults on chain.
 *
 * The vault is the source of truth for a position: whatever opened it - a rule's
 * signal through the executor, or a hand-sent entry - its entry, stop, target and
 * deadline are in `position()`, and nothing anywhere can change them. So the panel
 * and the chart read them there rather than from our database, which only knows
 * about the positions our executor opened.
 */
import { useCallback, useEffect, useState } from "react"
import type { Address } from "viem"
import { getPublicClient } from "wagmi/actions"

import { FACTORY_ABI, VAULT_ABI, VAULT_MARKETS, type VaultMarket } from "@/lib/vault"
import { wagmiConfig } from "@/lib/wallet"

/** The deployed factory, the same address on both chains (verified on each explorer). */
export const DEPLOYED_FACTORY: Record<number, Address> = {
  42161: "0x04C96936670c38982D1e7eF23caDd84d6891c818",
  4663: "0x04C96936670c38982D1e7eF23caDd84d6891c818",
}

const ZERO = "0x0000000000000000000000000000000000000000"
const REFRESH_MS = 20_000

export interface OpenPosition {
  market: string
  label: string
  chainName: string
  /** What the chart calls this market: ETHUSDT, BTCUSDT, or the stock's ticker. */
  chartSymbol: string
  vault: Address
  spentUsd: number
  entry: number
  stop: number
  target: number | null
  openedAt: number // unix seconds
  deadline: number // unix seconds
}

/** The chart a market's position belongs on. */
export function chartSymbolFor(m: Pick<VaultMarket, "market" | "stock">): string {
  const base = m.market.split("/")[0]
  if (m.stock) return base
  if (base === "WETH") return "ETHUSDT"
  if (base === "WBTC") return "BTCUSDT"
  return base
}

/** Position tuple as the vault returns it, prices in Chainlink's 8 decimals. */
export function fromTuple(
  m: VaultMarket,
  vault: Address,
  p: readonly [boolean, bigint, bigint, bigint, bigint, bigint, bigint, bigint],
): OpenPosition | null {
  const [open, spent, , entry, stop, target, openedAt, deadline] = p
  if (!open) return null
  return {
    market: m.market,
    label: m.label,
    chainName: m.chainName,
    chartSymbol: chartSymbolFor(m),
    vault,
    spentUsd: Number(spent) / 1e6,
    entry: Number(entry) / 1e8,
    stop: Number(stop) / 1e8,
    target: target === BigInt(0) ? null : Number(target) / 1e8,
    openedAt: Number(openedAt),
    deadline: Number(deadline),
  }
}

/** Unrealised P&L at `price`, long only: the vault buys the asset and sells it back. */
export function pnl(p: OpenPosition, price: number | undefined): { usd: number; pct: number } | null {
  if (!price || !p.entry) return null
  const pct = (price / p.entry - 1) * 100
  return { usd: (p.spentUsd * pct) / 100, pct }
}

/** "4m", "3h 10m", "2d 4h", or "due" once the deadline has passed. */
export function timeLeft(deadline: number, now = Date.now() / 1000): string {
  const s = Math.floor(deadline - now)
  if (s <= 0) return "due"
  const d = Math.floor(s / 86400)
  const h = Math.floor((s % 86400) / 3600)
  const m = Math.floor((s % 3600) / 60)
  if (d > 0) return `${d}d ${h}h`
  if (h > 0) return `${h}h ${m}m`
  return `${Math.max(1, m)}m`
}

async function readVaultPositions(owner: Address): Promise<OpenPosition[]> {
  const found: OpenPosition[] = []
  await Promise.all(
    VAULT_MARKETS.map(async (m) => {
      const factory = DEPLOYED_FACTORY[m.chainId]
      const client = getPublicClient(wagmiConfig, { chainId: m.chainId as 42161 | 4663 })
      if (!factory || !client) return
      try {
        const vault = (await client.readContract({
          address: factory,
          abi: FACTORY_ABI,
          functionName: "vaultOf",
          args: [owner, m.asset],
        })) as Address
        if (vault === ZERO) return
        const p = (await client.readContract({ address: vault, abi: VAULT_ABI, functionName: "position" })) as unknown as readonly [
          boolean, bigint, bigint, bigint, bigint, bigint, bigint, bigint,
        ]
        const open = fromTuple(m, vault, p)
        if (open) found.push(open)
      } catch {
        // A chain that does not answer this round is asked again on the next.
      }
    }),
  )
  return found.sort((a, b) => b.openedAt - a.openedAt)
}

/** The owner's open positions across every vault, refreshed every 20 seconds. */
export function useOpenPositions(owner: string | undefined | null): {
  positions: OpenPosition[]
  refresh: () => void
} {
  const [positions, setPositions] = useState<OpenPosition[]>([])
  const [tick, setTick] = useState(0)
  const refresh = useCallback(() => setTick((t) => t + 1), [])

  useEffect(() => {
    if (!owner) {
      setPositions([])
      return
    }
    let alive = true
    const load = () =>
      readVaultPositions(owner as Address).then((p) => {
        if (alive) setPositions(p)
      })
    void load()
    const id = window.setInterval(load, REFRESH_MS)
    return () => {
      alive = false
      window.clearInterval(id)
    }
  }, [owner, tick])

  return { positions, refresh }
}
