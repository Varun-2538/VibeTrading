"use client"

import { useCallback, useEffect, useState } from "react"
import { useAccount, useConnect, useDisconnect, useSignMessage, useSwitchChain } from "wagmi"

import {
  clearSession,
  fetchChallenge,
  loadSession,
  sessionFor,
  verifySignature,
  type Session,
} from "@/lib/session"
import { ARBITRUM_CHAIN_ID, pickConnector } from "@/lib/wallet"

export type SessionStatus =
  | "disconnected"
  | "wrong-chain"
  | "needs-signature"
  | "ready"

/**
 * Wallet sign-in, as one state machine.
 *
 * Rules belong to an address that has proved itself, so the panel needs a single
 * answer to "can this person be shown their rules yet", not four booleans that
 * can contradict each other.
 */
export function useSession() {
  const { address, isConnected, chainId } = useAccount()
  const { connect, connectors, isPending: connecting } = useConnect()
  const { disconnect } = useDisconnect()
  const { switchChain, isPending: switching } = useSwitchChain()
  const { signMessageAsync } = useSignMessage()

  const [session, setSession] = useState<Session | null>(null)
  const [signingIn, setSigningIn] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Reconciles the stored session against the wallet's current account.
  //
  // This is the case that quietly goes wrong otherwise: the user switches
  // account in their wallet, the token still names the previous address, and
  // they sit looking at rules that are not theirs. A mismatch discards the
  // token rather than merely hiding it, so a stale credential is not left in
  // storage. Note that `address` is undefined while wagmi is still restoring a
  // connection - that must not be read as a mismatch, or a reload would sign
  // everyone out.
  useEffect(() => {
    if (!address) {
      setSession(null)
      return
    }

    const stored = loadSession()
    if (stored && stored.address.toLowerCase() !== address.toLowerCase()) {
      clearSession()
      setSession(null)
      return
    }

    setSession(sessionFor(address))
  }, [address])

  const onWrongChain = isConnected && chainId !== ARBITRUM_CHAIN_ID

  const status: SessionStatus = !isConnected
    ? "disconnected"
    : onWrongChain
      ? "wrong-chain"
      : session
        ? "ready"
        : "needs-signature"

  const startConnect = useCallback(() => {
    setError(null)
    const hasInjectedProvider =
      typeof window !== "undefined" && Boolean((window as { ethereum?: unknown }).ethereum)
    const connector = pickConnector(connectors, hasInjectedProvider)
    if (!connector) {
      setError(
        "No wallet found. On a computer, install MetaMask or Rabby. On a phone, open this page from inside your wallet app's browser.",
      )
      return
    }
    connect({ connector })
  }, [connect, connectors])

  const signIn = useCallback(async () => {
    if (!address) return

    setSigningIn(true)
    setError(null)
    try {
      // The message is signed exactly as issued. Rebuilding it here would not
      // match the copy the server kept, and would never verify.
      const { message, nonce } = await fetchChallenge(address)
      const signature = await signMessageAsync({ message })
      setSession(await verifySignature({ address, nonce, signature }))
    } catch (err) {
      const message = err instanceof Error ? err.message : "Sign-in failed"
      // Declining in the wallet is a choice, not a fault, and the raw viem error
      // for it is a wall of text.
      setError(
        /rejected|denied|user cancel/i.test(message)
          ? "Sign-in cancelled."
          : message,
      )
    } finally {
      setSigningIn(false)
    }
  }, [address, signMessageAsync])

  const signOut = useCallback(() => {
    clearSession()
    setSession(null)
    setError(null)
    disconnect()
  }, [disconnect])

  /**
   * Drop the session without disconnecting the wallet.
   *
   * For a 401 from the API: the token has expired or the signing secret was
   * rotated, and the fix is another signature rather than another wallet.
   */
  const invalidate = useCallback(() => {
    clearSession()
    setSession(null)
  }, [])

  const switchToArbitrum = useCallback(() => {
    setError(null)
    switchChain({ chainId: ARBITRUM_CHAIN_ID })
  }, [switchChain])

  return {
    status,
    address,
    session,
    error,
    busy: connecting || switching || signingIn,
    connect: startConnect,
    signIn,
    signOut,
    invalidate,
    switchToArbitrum,
  }
}
