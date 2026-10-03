import { createConfig, http, type CreateConnectorFn } from "wagmi"
import { arbitrum } from "wagmi/chains"
// Narrow subpaths, not the "wagmi/connectors" barrel: the barrel re-exports
// every connector including Coinbase and Safe, which would pull their code into
// the bundle for wallets this feature does not offer.
import { injected } from "wagmi/connectors/injected"
import { walletConnect } from "wagmi/connectors/walletConnect"

export const ARBITRUM_CHAIN_ID = arbitrum.id
export const ARBITRUM_NAME = arbitrum.name

/**
 * Injected first, WalletConnect second.
 *
 * Injected covers browser extensions on desktop. WalletConnect is what makes
 * sign-in possible on a phone - Android has no extension wallets, so inside the
 * Play Store app it is the only route to a signature. It is only offered when a
 * project id is configured, so a local build without one still works on desktop.
 */
export function buildConnectors(projectId: string | undefined): CreateConnectorFn[] {
  const connectors: CreateConnectorFn[] = [injected()]
  if (projectId) {
    connectors.push(
      walletConnect({
        projectId,
        showQrModal: true,
        metadata: {
          name: "VibeTrading",
          description: "Liquidity levels and chart patterns for nine crypto pairs.",
          url: "https://app.vibetrading.club",
          icons: ["https://app.vibetrading.club/icons/icon-512.png"],
        },
      }),
    )
  }
  return connectors
}

export const wagmiConfig = createConfig({
  chains: [arbitrum],
  connectors: buildConnectors(process.env.NEXT_PUBLIC_WALLETCONNECT_PROJECT_ID),
  transports: {
    // The default public RPC. Nothing here reads chain state - the address and a
    // signature are all this feature needs - so no paid provider is required.
    [arbitrum.id]: http(),
  },
  // Next.js renders client components on the server too. Without this, wagmi
  // reads persisted state during SSR and the first client render disagrees with
  // the server's HTML.
  ssr: true,
})

/** 0x1234…abcd, for a header that has no room for 42 characters. */
export function shortAddress(address: string): string {
  return `${address.slice(0, 6)}…${address.slice(-4)}`
}
