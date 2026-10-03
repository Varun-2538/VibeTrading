import { beforeAll, describe, expect, it, vi } from "vitest"

type Listener = (event: any) => void
const listeners = new Map<string, Listener>()

const store = new Map<string, Response>()
const fakeCache = {
  add: vi.fn(async (url: string) => {
    store.set(url, new Response("<h1>offline</h1>", { headers: { "content-type": "text/html" } }))
  }),
  match: vi.fn(async (url: string) => store.get(url)),
}

// The Fetch spec forbids constructing a Request with mode "navigate" from script
// (only a real browser navigation produces one), so the fake hands the worker the
// one field it actually reads.
const navigation = { mode: "navigate", url: "https://app.vibetrading.club/" } as unknown as Request

beforeAll(async () => {
  Object.assign(globalThis, {
    self: {
      addEventListener: (type: string, fn: Listener) => listeners.set(type, fn),
      skipWaiting: vi.fn(),
      clients: { claim: vi.fn() },
    },
    caches: {
      open: vi.fn(async () => fakeCache),
      match: vi.fn(async (url: string) => store.get(url)),
      keys: vi.fn(async () => []),
      delete: vi.fn(),
    },
  })
  await import("../public/sw.js")
})

function dispatch(type: string, event: Record<string, unknown>) {
  const promises: Promise<unknown>[] = []
  let responded: Promise<Response> | undefined
  listeners.get(type)!({
    ...event,
    waitUntil: (p: Promise<unknown>) => promises.push(p),
    respondWith: (p: Promise<Response>) => (responded = p),
  })
  return { done: Promise.all(promises), responded }
}

describe("service worker", () => {
  it("precaches /offline on install", async () => {
    await dispatch("install", {}).done
    expect(fakeCache.add).toHaveBeenCalledWith("/offline")
  })

  it("serves the cached page when a navigation fails", async () => {
    globalThis.fetch = vi.fn(async () => {
      throw new TypeError("Failed to fetch")
    }) as typeof fetch
    const { responded } = dispatch("fetch", {
      request: navigation,
    })
    const res = await responded!
    expect(await res.text()).toContain("offline")
  })

  it("leaves non-navigation requests alone", () => {
    const { responded } = dispatch("fetch", {
      request: new Request("https://api.vibetrading.club/api/candles/BTCUSDT"),
    })
    expect(responded).toBeUndefined()
  })

  it("passes a successful navigation through untouched", async () => {
    globalThis.fetch = vi.fn(async () => new Response("live")) as typeof fetch
    const { responded } = dispatch("fetch", {
      request: navigation,
    })
    expect(await (await responded!).text()).toBe("live")
  })
})
