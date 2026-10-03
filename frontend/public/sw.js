/*
 * Offline fallback only.
 *
 * A Trusted Web Activity with no network shows Chrome's error page, which is
 * the one screen that makes the app look like a wrapped website. This worker
 * keeps exactly one thing - the /offline page - and hands it back when a
 * navigation cannot reach the server. It never caches API responses or chart
 * assets: a stale candle presented as live would be worse than an error.
 */
// The cached /offline page is refreshed only when this worker's bytes change,
// so bump the version here whenever app/offline/page.tsx changes.
const CACHE = "vt-offline-v1"
const OFFLINE_URL = "/offline"

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.add(OFFLINE_URL)).then(() => self.skipWaiting()),
  )
})

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  )
})

self.addEventListener("fetch", (event) => {
  if (event.request.mode !== "navigate") return
  event.respondWith(fetch(event.request).catch(() => caches.match(OFFLINE_URL)))
})
