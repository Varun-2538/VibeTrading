"use client"

import Link from "next/link"
import { Loader2, LogOut, Wallet } from "lucide-react"

import Wordmark from "@/components/wordmark"
import { useSession } from "@/hooks/use-session"
import { COMPANY } from "@/lib/company"
import { navigatePanel, type PanelTarget } from "@/lib/panel"
import { ARBITRUM_NAME, shortAddress } from "@/lib/wallet"

const API_DOCS_URL = "https://api.vibetrading.club/docs"

const PANEL_LINKS: { label: string; target: PanelTarget }[] = [
  { label: "Rules", target: "armed" },
  { label: "Backtests", target: "tests" },
  { label: "Vault", target: "vault" },
]

/*
 * The panel's top bar. The wallet control shows the connection wagmi already
 * shares app-wide; signing in stays in the strategy panel, which is where
 * the rules it unlocks live. The network badge reports the wallet's actual
 * chain rather than asserting one.
 */
export default function AppHeader({ onNavigate }: { onNavigate?: () => void }) {
  const { status, address, busy, error, connect, signOut, switchToArbitrum } = useSession()

  const go = (target: PanelTarget) => {
    onNavigate?.()
    navigatePanel(target)
  }

  return (
    <header className="flex h-12 shrink-0 items-center justify-between gap-3 border-b border-border bg-background/90 px-3 backdrop-blur lg:h-14 lg:px-4">
      <div className="flex min-w-0 items-center gap-3">
        <Link href="/" aria-label="VibeTrading home" className="shrink-0">
          <Wordmark />
        </Link>
        <span className="hidden rounded border border-primary/15 bg-secondary px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-[0.06em] text-primary sm:inline">
          {COMPANY.stage}
        </span>
      </div>

      <nav aria-label="Workspace" className="hidden items-center gap-1 text-[13px] lg:flex">
        <span
          aria-current="page"
          className="rounded border-b-2 border-primary bg-secondary px-3 py-1.5 font-medium text-primary"
        >
          Workspace
        </span>
        {PANEL_LINKS.map((l) => (
          <button
            key={l.target}
            type="button"
            onClick={() => go(l.target)}
            className="rounded px-3 py-1.5 text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
          >
            {l.label}
          </button>
        ))}
        <a
          href={API_DOCS_URL}
          className="rounded px-3 py-1.5 text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
        >
          API
        </a>
      </nav>

      <div className="flex shrink-0 items-center gap-2">
        {error && !address && (
          <span title={error} className="hidden max-w-[220px] truncate text-[11px] text-destructive md:inline">
            {error}
          </span>
        )}
        {status === "wrong-chain" ? (
          <button
            type="button"
            onClick={switchToArbitrum}
            className="hidden items-center gap-1.5 rounded border border-destructive/40 px-2 py-1 font-mono text-[11px] text-destructive sm:flex"
          >
            Switch to {ARBITRUM_NAME}
          </button>
        ) : (
          <span className="hidden items-center gap-1.5 rounded border border-border bg-secondary px-2 py-1 font-mono text-[11px] text-foreground sm:flex">
            <span
              className={`h-1.5 w-1.5 rounded-full ${address ? "animate-pulse bg-primary" : "bg-muted-foreground/50"}`}
            />
            {ARBITRUM_NAME}
          </span>
        )}

        {address ? (
          <button
            type="button"
            onClick={signOut}
            title={`${address} — disconnect`}
            className="group flex items-center gap-1.5 rounded border border-primary/25 bg-secondary px-2.5 py-1.5 font-mono text-xs text-foreground transition-colors hover:border-primary/50"
          >
            <Wallet className="h-3.5 w-3.5 text-primary" />
            {shortAddress(address)}
            <LogOut className="h-3 w-3 text-muted-foreground group-hover:text-foreground" />
            <span className="sr-only">Disconnect</span>
          </button>
        ) : (
          <button
            type="button"
            onClick={connect}
            disabled={busy}
            className="flex items-center gap-1.5 rounded bg-primary px-3 py-1.5 font-mono text-xs font-semibold text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-60"
          >
            {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Wallet className="h-3.5 w-3.5" />}
            Connect wallet
          </button>
        )}
      </div>
    </header>
  )
}
