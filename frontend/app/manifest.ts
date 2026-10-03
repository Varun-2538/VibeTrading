import type { MetadataRoute } from "next"

/**
 * Served at /manifest.webmanifest. Read by Chrome for "Add to home screen" and
 * by Bubblewrap when it generates the Android app, so the values here become
 * the launcher name, splash colour and orientation lock.
 */
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "VibeTrading",
    short_name: "VibeTrading",
    description:
      "Liquidity levels and double-bottom / double-top patterns, scoped to the candles you are looking at.",
    start_url: "/",
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
