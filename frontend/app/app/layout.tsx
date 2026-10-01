import type { Metadata } from "next"

export const metadata: Metadata = {
  title: "VibeTrading — Trading panel",
  description: "Live charts, liquidity levels and AI strategies across nine crypto pairs.",
  // The panel is a tool, not a landing page - keep it out of search results.
  robots: { index: false, follow: false },
}

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return children
}
