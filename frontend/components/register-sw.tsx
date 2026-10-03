"use client"

import { useEffect } from "react"

/**
 * Registers the offline-fallback worker in public/sw.js.
 *
 * Renders nothing. Registration failures are left to the browser's own
 * console: there is nothing the page can do about them, and the site works
 * without the worker - it only loses the offline page.
 */
export default function RegisterServiceWorker() {
  useEffect(() => {
    if (!("serviceWorker" in navigator)) return
    navigator.serviceWorker.register("/sw.js").catch(() => {})
  }, [])
  return null
}
