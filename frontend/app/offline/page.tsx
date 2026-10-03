import type { Metadata } from "next"

export const metadata: Metadata = {
  title: "VibeTrading — Offline",
  robots: { index: false, follow: false },
}

/**
 * Served by the service worker when a navigation fails.
 *
 * Styled inline rather than through globals.css: the worker caches only this
 * HTML, so the stylesheet and the fonts are exactly what will not load.
 */
export default function OfflinePage() {
  return (
    <main
      style={{
        minHeight: "100dvh",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 12,
        padding: "0 24px",
        textAlign: "center",
        background: "#040609",
        color: "#f7f7fa",
        fontFamily: "system-ui, sans-serif",
      }}
    >
      <svg width="40" height="40" viewBox="0 0 32 32" aria-hidden="true">
        <g stroke="#7af0ce" strokeWidth="3">
          <line x1="16" y1="3" x2="16" y2="29" />
          <rect x="9.5" y="11" width="13" height="10" fill="#040609" />
        </g>
      </svg>
      <p style={{ fontSize: 14, fontWeight: 600, margin: 0 }}>No connection</p>
      <p style={{ fontSize: 12, lineHeight: 1.6, maxWidth: 280, margin: 0, opacity: 0.7 }}>
        Live prices and analysis need a network. Reconnect and try again.
      </p>
      <a href="/" style={{ fontSize: 12, color: "#7af0ce", marginTop: 8 }}>
        Retry
      </a>
    </main>
  )
}
