const STORAGE_KEY = "vt.owner-key"

// Holds the key for this page's lifetime so storage is read once, and so the
// private-window fallback below stays stable instead of minting a new identity
// on every call.
let cached: string | null = null

/**
 * The key that namespaces this browser's strategy rules.
 *
 * This is NOT a login. It identifies a browser, not a person: clearing site
 * data or opening another browser gives you a different, empty set of rules,
 * and anyone holding the key can act as its owner. That is acceptable while a
 * rule can only raise an alert. It must be replaced with a real signed-in
 * identity before a rule can move money.
 */
export function getOwnerKey(): string {
  if (typeof window === "undefined") return ""
  if (cached) return cached

  try {
    const existing = window.localStorage.getItem(STORAGE_KEY)
    if (existing) {
      cached = existing
      return existing
    }

    cached = crypto.randomUUID()
    window.localStorage.setItem(STORAGE_KEY, cached)
    return cached
  } catch {
    // Private windows and blocked site data throw on access. Fall back to a
    // per-page key so the panel still works, accepting that rules created now
    // will not be found again after a reload.
    cached = crypto.randomUUID()
    return cached
  }
}
