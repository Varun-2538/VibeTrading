"use client"

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { useState } from "react"
import { WagmiProvider } from "wagmi"

import { wagmiConfig } from "@/lib/wallet"

/**
 * Wallet context for the trading panel.
 *
 * Mounted from app/app/layout.tsx rather than the root layout: the landing page
 * and the legal pages have no wallet features, and there is no reason to ship
 * wagmi to a reader of the privacy policy.
 */
export default function WalletProvider({ children }: { children: React.ReactNode }) {
  // Created in state, not at module scope: a module-level client is shared
  // across requests on the server, which leaks one user's cached data into
  // another's render.
  const [queryClient] = useState(() => new QueryClient())

  return (
    <WagmiProvider config={wagmiConfig}>
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    </WagmiProvider>
  )
}
