import type { MetadataRoute } from "next"

/**
 * Served at /manifest.webmanifest. Read by Chrome for "Add to home screen" and
 * by Bubblewrap when it generates the Android app, so the values here become
 * the launcher name, splash colour and orientation lock.
 */
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "VibeTrading Club",
    // Matches `name`: the full name is wanted even where it may be clipped.
    short_name: "VibeTrading Club",
    description:
      "Liquidity levels and double-bottom / double-top patterns, scoped to the candles you are looking at.",
    // A stable identity for the installed app, and an explicit scope. Without
    // `scope`, engines infer it from start_url and disagree: a navigation one
    // engine calls in-scope another calls a departure, and the Android app
    // answers a departure by drawing the browser's own close button and URL
    // bar over itself. Everything the panel links to - the legal pages, the
    // architecture page - sits under "/".
    id: "/",
    start_url: "/",
    scope: "/",
    display: "standalone",
    orientation: "portrait",
    // The panel's --background, so the splash and the first paint are one colour.
    background_color: "#040609",
    theme_color: "#040609",
    icons: [
      { src: "/icons/icon-192.png", sizes: "192x192", type: "image/png" },
      { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png" },
      { src: "/icons/icon-512-maskable.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  }
}
