import type { Metadata } from "next"

import WalletProvider from "@/components/wallet-provider"

export const metadata: Metadata = {
  title: "VibeTrading — Trading panel",
  description: "Live charts, liquidity levels and AI strategies across nine crypto pairs.",
  // The panel is a tool, not a landing page - keep it out of search results.
  robots: { index: false, follow: false },
}

export default function AppLayout({ children }: { children: React.ReactNode }) {
  // Scoped to the trading panel: the landing and legal pages have no wallet
  // features, so they should not carry wagmi in their bundle.
  return <WalletProvider>{children}</WalletProvider>
}
