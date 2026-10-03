/**
 * Paths the app-host rewrite must leave alone.
 *
 * The Android app is a Trusted Web Activity: Chrome reads the manifest, the
 * service worker and the Digital Asset Links file from this origin, and each
 * must come back as itself rather than as the panel's HTML. Kept as one list so
 * the middleware's matcher and its early return cannot disagree.
 */
const EXACT = new Set(["/manifest.webmanifest", "/sw.js", "/offline"])
const PREFIXES = ["/.well-known/"]

export function isPwaPath(pathname: string): boolean {
  if (EXACT.has(pathname)) return true
  return PREFIXES.some((prefix) => pathname.startsWith(prefix))
}
