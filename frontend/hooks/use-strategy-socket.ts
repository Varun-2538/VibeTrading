"use client"

import { useEffect, useRef } from "react"

import { API_BASE } from "@/lib/api"
import type { RuleEvent } from "@/lib/rules"

const PING_MS = 30_000
const MAX_BACKOFF_MS = 30_000
/** Policy violation: the server refused the socket because it did not authenticate. */
const CLOSE_UNAUTHENTICATED = 1008

/**
 * Subscribes to the signed-in owner's fired strategy signals.
 *
 * Signals arrive on /ws/rules, which is keyed by owner rather than symbol. They
 * used to ride the public /ws/{symbol} stream, where every browser watching a
 * pair received every other user's fired rules. Being keyed by owner also means
 * a rule on one pair still reaches you while you are looking at another, and one
 * socket covers the whole session instead of one per chart.
 *
 * The token goes in the opening frame rather than the URL: query strings are
 * written to access logs, and a browser cannot set headers on a WebSocket.
 *
 * Delivery is best effort by design. The database row is the source of truth and
 * the panel refetches its feed on mount and whenever this reconnects, so a
 * signal fired while disconnected is never lost - only its toast is.
 */
export function useStrategySocket(
  token: string | null,
  onSignal: (event: Partial<RuleEvent> & { event_id?: number }) => void,
  onReconnect?: () => void,
  onUnauthorized?: () => void,
) {
  // Held in refs so a changing callback identity cannot tear down the socket.
  const onSignalRef = useRef(onSignal)
  const onReconnectRef = useRef(onReconnect)
  const onUnauthorizedRef = useRef(onUnauthorized)

  useEffect(() => {
    onSignalRef.current = onSignal
    onReconnectRef.current = onReconnect
    onUnauthorizedRef.current = onUnauthorized
  }, [onSignal, onReconnect, onUnauthorized])

  useEffect(() => {
    if (!token) return

    let socket: WebSocket | null = null
    let pingTimer: ReturnType<typeof setInterval> | null = null
    let retryTimer: ReturnType<typeof setTimeout> | null = null
    let attempt = 0
    let hadConnected = false
    // Guards against a queued reconnect firing after unmount.
    let disposed = false

    const url = `${API_BASE.replace(/^http/, "ws")}/ws/rules`

    const connect = () => {
      if (disposed) return

      try {
        socket = new WebSocket(url)
      } catch {
        schedule()
        return
      }

      socket.onopen = () => {
        // The server closes the socket if this does not arrive promptly.
        socket?.send(JSON.stringify({ type: "auth", token }))

        pingTimer = setInterval(() => {
          if (socket?.readyState === WebSocket.OPEN) {
            socket.send(JSON.stringify({ type: "ping" }))
          }
        }, PING_MS)
      }

      socket.onmessage = (raw) => {
        try {
          const message = JSON.parse(raw.data)

          if (message?.type === "authenticated") {
            // Treated as the moment the socket is usable, rather than onopen: a
            // socket that opened but was refused never gets here, so a rejected
            // connection cannot masquerade as a successful reconnect.
            attempt = 0
            if (hadConnected) onReconnectRef.current?.()
            hadConnected = true
            return
          }

          if (message?.type === "strategy_signal" && message.data) {
            onSignalRef.current(message.data)
          }
        } catch {
          // A malformed frame is not worth surfacing; the feed stays correct.
        }
      }

      socket.onclose = (event) => {
        if (pingTimer) clearInterval(pingTimer)
        pingTimer = null

        // A rejected token will be rejected again just as fast. Retrying would
        // be an open loop against the server, so stop and let the panel ask for
        // a fresh signature instead.
        if (event.code === CLOSE_UNAUTHENTICATED) {
          onUnauthorizedRef.current?.()
          return
        }

        schedule()
      }

      // Let onclose own reconnection so a failed handshake retries once, not twice.
      socket.onerror = () => socket?.close()
    }

    const schedule = () => {
      if (disposed) return
      const delay = Math.min(1000 * 2 ** attempt, MAX_BACKOFF_MS)
      attempt += 1
      retryTimer = setTimeout(connect, delay)
    }

    connect()

    return () => {
      disposed = true
      if (pingTimer) clearInterval(pingTimer)
      if (retryTimer) clearTimeout(retryTimer)
      if (socket) {
        // Drop handlers first so the teardown close does not queue a reconnect.
        socket.onclose = null
        socket.onerror = null
        socket.close()
      }
    }
  }, [token])
}
