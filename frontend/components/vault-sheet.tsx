"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import { Loader2, ShieldCheck, Wallet } from "lucide-react"
import { useAccount, usePublicClient, useWriteContract } from "wagmi"
import type { Address } from "viem"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import {
  accountSummary,
  fmtR,
  fmtUsd,
  getAccount,
  getHealth,
  healthTrouble,
  listPositions,
  saveAccount,
  setKillSwitch,
  type ExecutionAccount,
  type ExecutionHealth,
  type ExecutionMode,
  type ExecutionPosition,
} from "@/lib/execution"
import { UnauthorizedError } from "@/lib/rules"
import {
  CURRENT_DISCLOSURE,
  ERC20_ABI,
  FACTORY_ABI,
  VAULT_ABI,
  VAULT_FACTORY,
  VAULT_MARKETS,
  disclosureHash,
  disclosureText,
  formatFeedPrice,
  formatUsdc,
  grantActive,
  grantExpiry,
  headroom,
  parseUsdc,
} from "@/lib/vault"

const GRANT_DAYS = 30
const ZERO = "0x0000000000000000000000000000000000000000"

interface VaultView {
  address: Address
  balance: bigint
  tvlCap: bigint
  operator: Address
  operatorExpiry: bigint
  maxNotional: bigint
  position: { open: boolean; qty: bigint; entryPrice: bigint; stopPrice: bigint; targetPrice: bigint }
}

/**
 * The vault, and the account that trades inside it.
 *
 * Everything on the left of this sheet is a transaction the owner sends from their
 * own wallet: deploying, funding, granting, revoking, withdrawing. We hold no key
 * that could do any of them. Everything on the right is a setting on our side, and
 * all of those are ceilings.
 *
 * The one thing the copy has to keep straight is that *armed* and *running* are
 * different states. An account can be armed while execution is switched off on the
 * server, and someone staring at a rule that has not traded needs to be told which
 * of the two is missing.
 */
export default function VaultSheet({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const { address } = useAccount()
  const client = usePublicClient()
  const { writeContractAsync, isPending: writing } = useWriteContract()

  const [market, setMarket] = useState(VAULT_MARKETS[0].market)
  const [vault, setVault] = useState<VaultView | null>(null)
  const [account, setAccount] = useState<ExecutionAccount | null>(null)
  const [health, setHealth] = useState<ExecutionHealth | null>(null)
  const [positions, setPositions] = useState<ExecutionPosition[]>([])
  const [amount, setAmount] = useState("100")
  const [accepted, setAccepted] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [note, setNote] = useState<string | null>(null)

  const asset = useMemo(
    () => VAULT_MARKETS.find((m) => m.market === market)?.asset as Address,
    [market],
  )
  const factory = VAULT_FACTORY as Address | ""

  const loadVault = useCallback(async () => {
    if (!client || !address || !factory) return
    try {
      const found = (await client.readContract({
        address: factory,
        abi: FACTORY_ABI,
        functionName: "vaultOf",
        args: [address, asset],
      })) as Address
      if (found === ZERO) {
        setVault(null)
        return
      }
      const reads = await Promise.all([
        client.readContract({ address: found, abi: VAULT_ABI, functionName: "stable" }),
        client.readContract({ address: found, abi: VAULT_ABI, functionName: "tvlCap" }),
        client.readContract({ address: found, abi: VAULT_ABI, functionName: "operator" }),
        client.readContract({ address: found, abi: VAULT_ABI, functionName: "operatorExpiry" }),
        client.readContract({ address: found, abi: VAULT_ABI, functionName: "maxNotional" }),
        client.readContract({ address: found, abi: VAULT_ABI, functionName: "position" }),
      ])
      const stable = reads[0] as Address
      const balance = (await client.readContract({
        address: stable,
        abi: ERC20_ABI,
        functionName: "balanceOf",
        args: [found],
      })) as bigint
      const p = reads[5] as unknown as [boolean, bigint, bigint, bigint, bigint, bigint, bigint, bigint]
      setVault({
        address: found,
        balance,
        tvlCap: reads[1] as bigint,
        operator: reads[2] as Address,
        operatorExpiry: reads[3] as bigint,
        maxNotional: reads[4] as bigint,
        position: { open: p[0], qty: p[2], entryPrice: p[3], stopPrice: p[4], targetPrice: p[5] },
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not read the vault")
    }
  }, [address, asset, client, factory])

  const loadServer = useCallback(async () => {
    try {
      const [a, h, p] = await Promise.all([getAccount(), getHealth(), listPositions()])
      setAccount(a)
      setHealth(h)
      setPositions(p)
    } catch (err) {
      if (err instanceof UnauthorizedError) {
        setAccount(null)
        return
      }
      setError(err instanceof Error ? err.message : "Could not read your execution account")
    }
  }, [])

  useEffect(() => {
    if (!open) return
    void loadVault()
    void loadServer()
  }, [open, loadVault, loadServer])

  async function send(label: string, run: () => Promise<unknown>) {
    setBusy(label)
    setError(null)
    setNote(null)
    try {
      await run()
      setNote(`${label} sent. It will show here once the chain confirms it.`)
      await loadVault()
    } catch (err) {
      setError(err instanceof Error ? err.message.split("\n")[0] : `${label} failed`)
    } finally {
      setBusy(null)
    }
  }

  const deploy = () =>
    send("Deploy", () =>
      writeContractAsync({
        address: factory as Address,
        abi: FACTORY_ABI,
        functionName: "deploy",
        args: [asset, disclosureHash()],
      }),
    )

  const fund = () => {
    const value = parseUsdc(amount)
    if (!vault || value === null || value <= 0n) {
      setError("Enter an amount in dollars, to at most six decimal places.")
      return
    }
    return send("Deposit", async () => {
      const stable = (await client!.readContract({
        address: vault.address,
        abi: VAULT_ABI,
        functionName: "stable",
      })) as Address
      await writeContractAsync({
        address: stable,
        abi: ERC20_ABI,
        functionName: "approve",
        args: [vault.address, value],
      })
      await writeContractAsync({
        address: vault.address,
        abi: VAULT_ABI,
        functionName: "deposit",
        args: [value],
      })
    })
  }

  const operator = (account?.operator_address ?? null) as Address | null

  const grant = () => {
    if (!operator) {
      setError("There is no executor address to grant to yet.")
      return
    }
    return send("Grant", () =>
      writeContractAsync({
        address: vault!.address,
        abi: VAULT_ABI,
        functionName: "setOperator",
        // Read off the server rather than configured in the browser: one source of
        // truth, so a redeployed executor cannot leave owners granting permission to
        // an address that no longer signs anything.
        args: [operator, grantExpiry(GRANT_DAYS)],
      }),
    )
  }

  const revoke = () =>
    send("Revoke", () =>
      writeContractAsync({ address: vault!.address, abi: VAULT_ABI, functionName: "revokeOperator" }),
    )

  const withdrawAll = () =>
    send("Withdraw", async () => {
      const stable = (await client!.readContract({
        address: vault!.address,
        abi: VAULT_ABI,
        functionName: "stable",
      })) as Address
      await writeContractAsync({
        address: vault!.address,
        abi: VAULT_ABI,
        functionName: "withdraw",
        args: [stable, vault!.balance, address as Address],
      })
    })

  async function setMode(mode: ExecutionMode) {
    if (!account) return
    setBusy("Mode")
    setError(null)
    try {
      setAccount(await saveAccount({ ...toSettings(account), mode }))
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not change the mode")
    } finally {
      setBusy(null)
    }
  }

  async function flipKill(on: boolean) {
    setBusy("Kill")
    try {
      setAccount(await setKillSwitch(on))
      setHealth(await getHealth())
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not flip the switch")
    } finally {
      setBusy(null)
    }
  }

  const trouble = healthTrouble(health)
  // Active *and* ours. A grant to some other address is not permission we hold, and
  // showing it as one would be the most misleading thing on this screen.
  const grantOn = Boolean(
    vault &&
      operator &&
      vault.operator.toLowerCase() === operator.toLowerCase() &&
      grantActive({ operator: vault.operator, operatorExpiry: vault.operatorExpiry }),
  )

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-md">
        <SheetHeader>
          <SheetTitle className="flex items-center gap-2 text-sm">
            <ShieldCheck className="h-4 w-4" /> Vault and execution
          </SheetTitle>
          <SheetDescription className="text-xs leading-relaxed">
            Your funds stay in a contract you own. We can only swap inside it, within the caps you set,
            and you can revoke that on-chain at any time without our help.
          </SheetDescription>
        </SheetHeader>

        <div className="space-y-5 px-4 pb-8 pt-2">
          {!factory && (
            <p className="rounded border border-border bg-secondary/40 p-2 text-[11px] leading-relaxed text-muted-foreground">
              No vault factory is configured for this environment yet, so there is nothing to deploy against.
              The contract is in <span className="font-mono">contracts/</span> and goes to a testnet first.
            </p>
          )}

          <section className="space-y-2">
            <span className="text-[11px] text-muted-foreground">Market</span>
            <div className="flex gap-1.5">
              {VAULT_MARKETS.map((m) => (
                <Button
                  key={m.market}
                  size="sm"
                  variant={market === m.market ? "default" : "outline"}
                  className="h-7 flex-1 text-xs"
                  onClick={() => setMarket(m.market)}
                >
                  {m.label}
                </Button>
              ))}
            </div>
            <p className="text-[10px] leading-relaxed text-muted-foreground">
              One vault per market, on purpose: a vault holding one asset is small enough to read end to
              end, and a position never competes with another for the same balance.
            </p>
          </section>

          {!vault ? (
            <section className="space-y-2">
              <span className="text-[11px] text-muted-foreground">No vault for this market yet</span>
              <label className="flex items-start gap-2 text-[11px] leading-relaxed text-foreground">
                <input
                  type="checkbox"
                  checked={accepted}
                  onChange={(e) => setAccepted(e.target.checked)}
                  className="mt-0.5"
                />
                <span>
                  I have read and accept this ({CURRENT_DISCLOSURE}). Its hash is stored in the vault, so
                  which wording you agreed to is a fact on-chain rather than a row in our database.
                </span>
              </label>
              <pre className="max-h-40 overflow-y-auto whitespace-pre-wrap rounded border border-border bg-secondary/40 p-2 text-[10px] leading-relaxed text-muted-foreground">
                {disclosureText()}
              </pre>
              <Button
                size="sm"
                className="h-7 w-full text-xs"
                disabled={!accepted || !factory || !address || writing || busy !== null}
                onClick={deploy}
              >
                {busy === "Deploy" ? <Loader2 className="h-3 w-3 animate-spin" /> : "Deploy my vault"}
              </Button>
            </section>
          ) : (
            <>
              <section className="space-y-1.5">
                <div className="flex items-baseline justify-between">
                  <span className="text-[11px] text-muted-foreground">Vault</span>
                  <span className="font-mono text-[10px] text-muted-foreground">
                    {vault.address.slice(0, 6)}…{vault.address.slice(-4)}
                  </span>
                </div>
                <table className="w-full text-[11px]">
                  <tbody className="font-mono">
                    <Row label="Balance" value={formatUsdc(vault.balance)} />
                    <Row label="Room under the cap" value={formatUsdc(headroom(vault))} />
                    <Row label="Max per trade" value={formatUsdc(vault.maxNotional)} />
                    <Row
                      label="Our permission"
                      value={grantOn ? `active, expires ${expiryLabel(vault.operatorExpiry)}` : "none"}
                    />
                  </tbody>
                </table>
                <div className="flex gap-1.5">
                  <Input
                    value={amount}
                    onChange={(e) => setAmount(e.target.value)}
                    className="h-7 px-2 font-mono text-xs"
                    inputMode="decimal"
                  />
                  <Button size="sm" variant="outline" className="h-7 text-xs" disabled={busy !== null} onClick={fund}>
                    Deposit
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    className="h-7 text-xs"
                    disabled={busy !== null || vault.balance === 0n}
                    onClick={withdrawAll}
                  >
                    Withdraw all
                  </Button>
                </div>
                <div className="flex gap-1.5">
                  {grantOn ? (
                    <Button size="sm" variant="outline" className="h-7 flex-1 text-xs" disabled={busy !== null} onClick={revoke}>
                      Revoke our permission
                    </Button>
                  ) : (
                    <Button
                      size="sm"
                      className="h-7 flex-1 text-xs"
                      disabled={busy !== null || !operator}
                      onClick={grant}
                      title={operator ? undefined : "No executor address is published yet"}
                    >
                      Allow us to trade for {GRANT_DAYS} days
                    </Button>
                  )}
                </div>
                <p className="text-[10px] leading-relaxed text-muted-foreground">
                  A grant expires by itself. Nothing renews it silently, and revoking needs no cooperation
                  from us.
                </p>
              </section>

              {vault.position.open && (
                <section className="space-y-1">
                  <span className="text-[11px] text-muted-foreground">Open in the vault</span>
                  <table className="w-full text-[11px]">
                    <tbody className="font-mono">
                      <Row label="Entry" value={formatFeedPrice(vault.position.entryPrice)} />
                      <Row label="Stop" value={formatFeedPrice(vault.position.stopPrice)} />
                      <Row label="Target" value={formatFeedPrice(vault.position.targetPrice)} />
                    </tbody>
                  </table>
                  <p className="text-[10px] leading-relaxed text-muted-foreground">
                    The stop and the target are written in the contract and cannot be moved — not by us,
                    and not by you. Anyone can close the position once one of them is reached, so it does
                    not depend on our server being up.
                  </p>
                </section>
              )}
            </>
          )}

          <section className="space-y-2 border-t border-border pt-4">
            <span className="text-[11px] text-muted-foreground">Execution</span>
            <p className="text-[11px] leading-relaxed text-foreground">{accountSummary(account)}</p>
            {trouble && (
              <p className="rounded border border-destructive/40 bg-destructive/10 p-2 text-[11px] leading-relaxed text-destructive">
                {trouble}
              </p>
            )}
            {account && (
              <>
                <div className="flex gap-1.5">
                  {(["off", "shadow", "live"] as ExecutionMode[]).map((mode) => (
                    <Button
                      key={mode}
                      size="sm"
                      variant={account.mode === mode ? "default" : "outline"}
                      className="h-7 flex-1 text-xs"
                      disabled={busy !== null || (mode === "live" && !grantOn)}
                      onClick={() => setMode(mode)}
                      title={mode === "live" && !grantOn ? "Grant us permission in the vault first" : undefined}
                    >
                      {mode === "off" ? "Off" : mode === "shadow" ? "Shadow" : "Live"}
                    </Button>
                  ))}
                </div>
                <p className="text-[10px] leading-relaxed text-muted-foreground">
                  Shadow records what would have been traded and sends nothing. It is worth a week before
                  live: it measures what your strategy actually costs, against what the backtest assumed.
                </p>
                <Button
                  size="sm"
                  variant={account.kill_switch ? "default" : "outline"}
                  className="h-7 w-full text-xs"
                  disabled={busy !== null}
                  onClick={() => flipKill(!account.kill_switch)}
                >
                  {account.kill_switch ? "Kill switch is on — turn it off" : "Stop opening anything now"}
                </Button>
              </>
            )}
          </section>

          {positions.length > 0 && (
            <section className="space-y-1 border-t border-border pt-4">
              <span className="text-[11px] text-muted-foreground">Recent positions</span>
              <table className="w-full text-[11px]">
                <tbody className="font-mono">
                  {positions.slice(0, 8).map((p) => (
                    <tr key={p.id} className="border-t border-border">
                      <td className="py-1 pr-2 font-sans text-muted-foreground">
                        {p.symbol} {p.mode === "shadow" ? "· shadow" : ""}
                      </td>
                      <td className="py-1 pr-2">{p.status}</td>
                      <td className="py-1">{p.status === "closed" ? fmtR(p.realised_r) : fmtUsd(p.notional_usd)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          )}

          {note && <p className="text-[11px] text-muted-foreground">{note}</p>}
          {error && <p className="text-[11px] text-destructive">{error}</p>}
        </div>
      </SheetContent>
    </Sheet>
  )
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <tr className="border-t border-border">
      <td className="py-1 pr-2 font-sans text-muted-foreground">{label}</td>
      <td className="py-1 text-right">{value}</td>
    </tr>
  )
}

function expiryLabel(expiry: bigint): string {
  return new Date(Number(expiry) * 1000).toISOString().slice(0, 10)
}

function toSettings(account: ExecutionAccount) {
  return {
    mode: account.mode,
    equity_usd: account.equity_usd,
    max_notional_usd: account.max_notional_usd,
    max_concurrent_positions: account.max_concurrent_positions,
    max_trades_per_day: account.max_trades_per_day,
    daily_loss_limit_usd: account.daily_loss_limit_usd,
  }
}
