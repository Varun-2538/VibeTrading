import { createConfig, http } from "wagmi"
import { arbitrum } from "wagmi/chains"
// The narrow subpath, not the "wagmi/connectors" barrel: the barrel re-exports
// every connector including WalletConnect and Coinbase, which would pull their
// code into the bundle for a feature that only supports browser extensions.
import { injected } from "wagmi/connectors/injected"

export const ARBITRUM_CHAIN_ID = arbitrum.id
export const ARBITRUM_NAME = arbitrum.name

export const wagmiConfig = createConfig({
  chains: [arbitrum],
  connectors: [injected()],
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
