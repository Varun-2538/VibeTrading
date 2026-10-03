"use client"

import { useEffect } from "react"

/**
 * True on the app host (and localhost, where the panel is served for local
 * dev) - the hosts whose offline page the service worker's copy is written
 * for. False on the landing site, which needs no offline page.
 */
export function shouldRegisterServiceWorker(hostname: string): boolean {
  return hostname.startsWith("app.") || hostname === "localhost"
}

/**
 * Registers the offline-fallback worker in public/sw.js.
 *
 * The root layout is shared by the landing site (vibetrading.club) and the
 * panel (app.vibetrading.club), but the offline page is written for the
 * panel - the landing site does not need it and the copy would not fit it -
 * so registration only runs on the app host.
 *
 * Renders nothing. Registration failures are left to the browser's own
 * console: there is nothing the page can do about them, and the site works
 * without the worker - it only loses the offline page.
 */
export default function RegisterServiceWorker() {
  useEffect(() => {
    if (!("serviceWorker" in navigator)) return
    if (!shouldRegisterServiceWorker(window.location.hostname)) return
    navigator.serviceWorker.register("/sw.js").catch(() => {})
  }, [])
  return null
}
