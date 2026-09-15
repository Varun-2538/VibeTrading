import type { Metadata } from "next"

import WalletProvider from "@/components/wallet-provider"

export const metadata: Metadata = {
  title: "VibeTrading — Trading panel",
  description: "Live charts, liquidity levels and AI strategies across nine crypto pairs.",
  // The panel is a tool, not a landing page - keep it out of search results.
  robots: { index: false, follow: false },
  // Chrome's auto-translate rewrites the panel's labels, and on a trading
  // screen that is corruption rather than a courtesy: on a Hindi device it
  // turned the 1m timeframe into "1 मीटर" - one metre - and 1d into "-1 डी".
  // The legal pages are prose and are left translatable.
  other: { google: "notranslate" },
}

export default function AppLayout({ children }: { children: React.ReactNode }) {
  // Scoped to the trading panel: the landing and legal pages have no wallet
  // features, so they should not carry wagmi in their bundle.
  return <WalletProvider>{children}</WalletProvider>
}
