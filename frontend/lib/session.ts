import { API_BASE, readError } from "@/lib/api"

const STORAGE_KEY = "vt.session"

/**
 * A signed-in wallet session.
 *
 * The token is held in localStorage, so it survives a reload and any script
 * running on this origin could read it. That is the same exposure as the
 * browser key it replaces, and the ceiling on the damage is still an alert rule:
 * a token authorises reading and editing rules, and nothing else. It must not be
 * the storage choice once a rule can spend money.
 */
export interface Session {
  token: string
  address: string
  expiresAt: string
}

let cached: Session | null = null

function isExpired(session: Session): boolean {
  const expires = new Date(session.expiresAt).getTime()
  if (Number.isNaN(expires)) return true
  // A minute of slack, so a token that dies mid-request fails on the server
  // rather than being sent and rejected in a way we would have to unpick.
  return expires - 60_000 <= Date.now()
}

export function loadSession(): Session | null {
  if (typeof window === "undefined") return null
  if (cached) return isExpired(cached) ? (clearSession(), null) : cached

  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return null

    const parsed = JSON.parse(raw) as Session
    if (!parsed?.token || !parsed?.address || isExpired(parsed)) {
      clearSession()
      return null
    }

    cached = parsed
    return parsed
  } catch {
    // Corrupt JSON, or storage blocked in a private window.
    return null
  }
}

export function saveSession(session: Session): void {
  cached = session
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(session))
  } catch {
    // Private windows throw. The in-memory copy still serves this page.
  }
}

export function clearSession(): void {
  cached = null
  try {
    window.localStorage.removeItem(STORAGE_KEY)
  } catch {
    // Nothing to do - there was no durable copy to remove.
  }
}

export function getToken(): string | null {
  return loadSession()?.token ?? null
}

/**
 * The session for this wallet, or null.
 *
 * Compared case-insensitively because the wallet reports a checksummed address
 * while the server stores a lowercased one. A session belonging to a different
 * address is not returned - switching accounts must not inherit the previous
 * account's rules.
 */
export function sessionFor(address: string | undefined): Session | null {
  const session = loadSession()
  if (!session || !address) return null
  return session.address.toLowerCase() === address.toLowerCase() ? session : null
}

/** Ask the server for the message to sign. */
export async function fetchChallenge(
  address: string,
): Promise<{ message: string; nonce: string }> {
  const res = await fetch(
    `${API_BASE}/api/auth/nonce?address=${encodeURIComponent(address)}`,
  )
  if (!res.ok) throw new Error(await readError(res, "Could not start sign-in"))
  return res.json()
}

/**
 * Exchange a signature for a session token.
 *
 * The signed message is not sent: the server kept the copy it issued and
 * compares against that, which is why the client must sign what it was given
 * verbatim rather than rebuilding the text.
 */
export async function verifySignature(input: {
  address: string
  nonce: string
  signature: string
}): Promise<Session> {
  const res = await fetch(`${API_BASE}/api/auth/verify`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  })
  if (!res.ok) throw new Error(await readError(res, "Could not verify your signature"))

  const data = (await res.json()) as { token: string; address: string; expires_at: string }
  const session: Session = {
    token: data.token,
    address: data.address,
    expiresAt: data.expires_at,
  }
  saveSession(session)
  return session
}
