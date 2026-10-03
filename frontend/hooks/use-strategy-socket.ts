"use client"

import { useEffect, useRef } from "react"

import { API_BASE } from "@/lib/api"
import type { RuleEvent } from "@/lib/rules"

const PING_MS = 30_000
const MAX_BACKOFF_MS = 30_000

/**
 * Subscribes to fired strategy signals for one symbol.
 *
 * Signals ride the general /ws/{symbol} stream rather than /ws/strategy/{symbol}:
 * that second endpoint accepts its socket directly without registering with the
 * server's connection manager, so broadcasts never reach it. Filtering one
 * message type here is cheaper than reworking a live endpoint.
 *
 * Delivery is best effort by design. The database row is the source of truth and
 * the panel refetches its feed on mount and whenever this reconnects, so a
 * signal fired while disconnected is never lost - only its toast is.
 */
export function useStrategySocket(
  symbol: string,
  onSignal: (event: Partial<RuleEvent> & { event_id?: number }) => void,
  onReconnect?: () => void,
) {
  // Held in refs so a changing callback identity cannot tear down the socket.
  const onSignalRef = useRef(onSignal)
  const onReconnectRef = useRef(onReconnect)

  useEffect(() => {
    onSignalRef.current = onSignal
    onReconnectRef.current = onReconnect
  }, [onSignal, onReconnect])

  useEffect(() => {
    if (!symbol) return

    let socket: WebSocket | null = null
    let pingTimer: ReturnType<typeof setInterval> | null = null
    let retryTimer: ReturnType<typeof setTimeout> | null = null
    let attempt = 0
    let hadConnected = false
    // Guards against a queued reconnect firing after unmount.
    let disposed = false

    const url = `${API_BASE.replace(/^http/, "ws")}/ws/${symbol}`

    const connect = () => {
      if (disposed) return

      try {
        socket = new WebSocket(url)
      } catch {
        schedule()
        return
      }

      socket.onopen = () => {
        attempt = 0
        // Only refetch on a genuine reconnect; the panel already loads on mount.
        if (hadConnected) onReconnectRef.current?.()
        hadConnected = true

        pingTimer = setInterval(() => {
          if (socket?.readyState === WebSocket.OPEN) {
            socket.send(JSON.stringify({ type: "ping" }))
          }
        }, PING_MS)
      }

      socket.onmessage = (raw) => {
        try {
          const message = JSON.parse(raw.data)
          if (message?.type === "strategy_signal" && message.data) {
            onSignalRef.current(message.data)
          }
        } catch {
          // A malformed frame is not worth surfacing; the feed stays correct.
        }
      }

      socket.onclose = () => {
        if (pingTimer) clearInterval(pingTimer)
        pingTimer = null
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
  }, [symbol])
}
