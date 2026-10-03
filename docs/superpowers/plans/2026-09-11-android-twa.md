# Android app on Google Play (TWA) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish the existing `app.vibetrading.club` trading panel on Google Play as a Trusted Web Activity, with wallet sign-in that works on Android.

**Architecture:** The Next.js frontend becomes an installable PWA (manifest, icons, offline-fallback service worker, Digital Asset Links). A Bubblewrap-generated Android project in `android/` wraps that URL in a TWA. WalletConnect is added beside the injected connector so a phone can sign the SIWE message through a wallet app. Nothing in the backend changes.

**Tech Stack:** Next.js 15 (App Router), wagmi 3 + `@walletconnect/ethereum-provider`, vitest (new, for the pure pieces), sharp (icon rendering), `@bubblewrap/cli` (JDK 17 + Android SDK, installed by Bubblewrap), Google Play Console.

**Spec:** `docs/superpowers/specs/2026-09-11-android-twa-design.md`

## Global Constraints

- The app opens `https://app.vibetrading.club/` — the panel, never the landing page.
- Android package id is `club.vibetrading.app`.
- Portrait only, in both the web manifest and `twa-manifest.json`.
- `theme_color` and `background_color` are `#040609` (the hex of `--background: oklch(0.12 0.01 264)` in `frontend/app/globals.css`); icon ink is `#7af0ce` (from `frontend/app/icon.svg`).
- The service worker caches **only** the `/offline` page. No API responses, no candles, no chart assets.
- No push notifications, no iOS, no landscape, no UI changes to the panel.
- Keystores never enter git. `.gitignore` gets `*.keystore` and `*.jks`.
- Frontend package manager is **npm** (there is a `package-lock.json`; run commands from `frontend/`).
- Commit messages follow the repo style: one imperative sentence, no `feat:` prefix, ending with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
- Tasks 1–5 and 7 are code and can run in any order among themselves except where noted; Task 6 onward needs the code deployed to Vercel first (Task 6 says when).

---

## File map

| Path | Responsibility |
|---|---|
| `frontend/vitest.config.ts`, `frontend/package.json` | Test runner for the pure pieces (new) |
| `frontend/lib/pwa-paths.ts` | `isPwaPath(pathname)` — the list of paths the app-host rewrite must leave alone |
| `frontend/middleware.ts` | Calls `isPwaPath` before rewriting; matcher also excludes them |
| `frontend/app/manifest.ts` | Web app manifest at `/manifest.webmanifest` |
| `frontend/scripts/make-icons.mjs` | Renders `public/icons/*.png` from the candle mark |
| `frontend/public/icons/` | 192, 512, 512-maskable PNGs (generated, committed) |
| `frontend/app/offline/page.tsx` | Self-contained "no connection" page |
| `frontend/public/sw.js` | Precaches `/offline`, serves it on failed navigations |
| `frontend/components/register-sw.tsx` | Registers `/sw.js` once, client-side |
| `frontend/app/layout.tsx` | Mounts `RegisterServiceWorker` |
| `frontend/lib/wallet.ts` | `buildConnectors(projectId)` and `pickConnector(connectors, hasInjectedProvider)` |
| `frontend/hooks/use-session.ts` | `startConnect` uses `pickConnector` |
| `frontend/app/legal/privacy/page.tsx` | One sentence on WalletConnect relay |
| `frontend/public/.well-known/assetlinks.json` | Digital Asset Links (upload key + Play signing key) |
| `android/` | Bubblewrap project; `twa-manifest.json` is the source of truth |
| `store/` | Feature graphic, screenshots, listing copy |
| `.gitignore`, `.env.prod.example`, `README.md` | Ignore rules, env documentation, Android section |

---

### Task 1: Test runner and middleware bypass for PWA paths

The app-host middleware rewrites every path onto `/app/…`, so `/manifest.webmanifest`, `/sw.js`, `/offline` and `/.well-known/assetlinks.json` would all return the panel's HTML. This task makes those paths pass through, and installs vitest because it is the first thing in the frontend worth a unit test.

**Files:**
- Create: `frontend/vitest.config.ts`
- Create: `frontend/lib/pwa-paths.ts`
- Create: `frontend/tests/pwa-paths.test.ts`
- Create: `frontend/tests/middleware.test.ts`
- Modify: `frontend/package.json` (scripts + devDependencies)
- Modify: `frontend/middleware.ts`

**Interfaces:**
- Produces: `isPwaPath(pathname: string): boolean` in `@/lib/pwa-paths`. True for `/manifest.webmanifest`, `/sw.js`, `/offline`, and anything under `/.well-known/`.

- [ ] **Step 1: Install vitest and add the script**

Run from `frontend/`:
```bash
npm install -D vitest@^3
```
Add to `package.json` `"scripts"`:
```json
"test": "vitest run"
```

- [ ] **Step 2: Create `frontend/vitest.config.ts`**

```ts
import { fileURLToPath } from "node:url"
import { defineConfig } from "vitest/config"

// Mirrors the "@/..." alias in tsconfig.json so tests import the same way the app does.
export default defineConfig({
  resolve: {
    alias: { "@": fileURLToPath(new URL(".", import.meta.url)) },
  },
  test: {
    environment: "node",
    include: ["tests/**/*.test.ts"],
  },
})
```

- [ ] **Step 3: Write the failing tests**

`frontend/tests/pwa-paths.test.ts`:
```ts
import { describe, expect, it } from "vitest"

import { isPwaPath } from "@/lib/pwa-paths"

describe("isPwaPath", () => {
  it.each([
    "/manifest.webmanifest",
    "/sw.js",
    "/offline",
    "/.well-known/assetlinks.json",
  ])("passes %s through untouched", (path) => {
    expect(isPwaPath(path)).toBe(true)
  })

  it.each(["/", "/app", "/legal/privacy", "/offline-chart", "/wellknown"])(
    "still rewrites %s",
    (path) => {
      expect(isPwaPath(path)).toBe(false)
    },
  )
})
```

`frontend/tests/middleware.test.ts`:
```ts
import { NextRequest } from "next/server"
import { describe, expect, it } from "vitest"

import { middleware } from "@/middleware"

// NextResponse.rewrite() marks the response with this header; NextResponse.next() does not.
const REWRITE_HEADER = "x-middleware-rewrite"

function onAppHost(path: string) {
  return new NextRequest(`https://app.vibetrading.club${path}`)
}

describe("middleware on the app host", () => {
  it("still rewrites the root onto the panel", () => {
    const res = middleware(onAppHost("/"))
    expect(res.headers.get(REWRITE_HEADER)).toContain("/app")
  })

  it.each(["/manifest.webmanifest", "/sw.js", "/offline", "/.well-known/assetlinks.json"])(
    "does not rewrite %s",
    (path) => {
      const res = middleware(onAppHost(path))
      expect(res.headers.get(REWRITE_HEADER)).toBeNull()
    },
  )
})
```

- [ ] **Step 4: Run tests to verify they fail**

Run from `frontend/`: `npm test`
Expected: FAIL — `Cannot find module '@/lib/pwa-paths'`, and the middleware `does not rewrite` cases fail because the rewrite header is present.

- [ ] **Step 5: Create `frontend/lib/pwa-paths.ts`**

```ts
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
```

- [ ] **Step 6: Update `frontend/middleware.ts`**

Add the import at the top:
```ts
import { isPwaPath } from "@/lib/pwa-paths"
```

Change the early return so PWA paths are skipped on the app host:
```ts
  if (!isAppHost || isPwaPath(pathname)) return NextResponse.next()
```

Replace the `config` block. The matcher is what stops the middleware running at all, so it must exclude the same paths; the early return above is what the test exercises and what protects against the two lists drifting:
```ts
export const config = {
  // Skip static assets, the API namespace, and the files a Trusted Web Activity
  // reads from the origin (manifest, service worker, offline page, asset links).
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|manifest\\.webmanifest|sw\\.js|offline$|\\.well-known/|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico)$).*)",
  ],
}
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `npm test`
Expected: both files PASS (9 tests).

- [ ] **Step 8: Confirm the build still accepts the middleware**

Run: `npm run build`
Expected: completes; the output lists `ƒ Middleware`. Next rejects an invalid matcher at build time, so this is the check that the regex is well-formed.

- [ ] **Step 9: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/vitest.config.ts frontend/lib/pwa-paths.ts frontend/middleware.ts frontend/tests/
git commit -m "Let PWA files through the app-host rewrite

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Web app manifest and icons

**Files:**
- Create: `frontend/app/manifest.ts`
- Create: `frontend/scripts/make-icons.mjs`
- Create: `frontend/public/icons/icon-192.png`, `icon-512.png`, `icon-512-maskable.png` (generated)
- Create: `frontend/tests/manifest.test.ts`
- Modify: `frontend/package.json` (devDependency `sharp`, script `icons`)

**Interfaces:**
- Produces: `GET /manifest.webmanifest` on both hosts. Task 6 points Bubblewrap at `https://app.vibetrading.club/manifest.webmanifest`.

- [ ] **Step 1: Write the failing test**

`frontend/tests/manifest.test.ts`:
```ts
import { existsSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"

import manifest from "@/app/manifest"

const publicDir = fileURLToPath(new URL("../public", import.meta.url))

describe("web app manifest", () => {
  const m = manifest()

  it("is installable as a standalone portrait app", () => {
    expect(m.name).toBe("VibeTrading")
    expect(m.short_name).toBe("VibeTrading")
    expect(m.start_url).toBe("/")
    expect(m.display).toBe("standalone")
    expect(m.orientation).toBe("portrait")
    expect(m.theme_color).toBe("#040609")
    expect(m.background_color).toBe("#040609")
  })

  it("lists 192, 512 and a maskable 512 icon", () => {
    const sizes = m.icons?.map((i) => `${i.sizes}:${i.purpose ?? "any"}`)
    expect(sizes).toEqual(["192x192:any", "512x512:any", "512x512:maskable"])
  })

  it("only lists icons that exist on disk", () => {
    for (const icon of m.icons ?? []) {
      expect(existsSync(`${publicDir}${icon.src}`), icon.src).toBe(true)
    }
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- manifest`
Expected: FAIL — `Cannot find module '@/app/manifest'`.

- [ ] **Step 3: Create `frontend/app/manifest.ts`**

```ts
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
```

- [ ] **Step 4: Install sharp and add the icon script**

Run from `frontend/`:
```bash
npm install -D sharp@^0.34
```
Add to `package.json` `"scripts"`:
```json
"icons": "node scripts/make-icons.mjs"
```

- [ ] **Step 5: Create `frontend/scripts/make-icons.mjs`**

```js
// Renders the PWA icons from the candle mark in app/icon.svg.
//
// The mark is redrawn here rather than rasterised from the favicon file: that
// file has its own rounded background and 32px-tuned stroke. Android masks
// launcher icons itself, so these are square, and the maskable variant keeps the
// mark inside the central 50% so no mask shape clips it.
import { mkdir } from "node:fs/promises"
import sharp from "sharp"

const BG = "#040609"
const INK = "#7af0ce"
const OUT = new URL("../public/icons/", import.meta.url)

function candle(size, scale) {
  const s = (size * scale) / 32
  const offset = (size - 32 * s) / 2
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
  <rect width="${size}" height="${size}" fill="${BG}"/>
  <g transform="translate(${offset} ${offset}) scale(${s})" stroke="${INK}" stroke-width="3" stroke-linecap="butt">
    <line x1="16" y1="3" x2="16" y2="29"/>
    <rect x="9.5" y="11" width="13" height="10" fill="${BG}"/>
  </g>
</svg>`
}

async function write(name, size, scale) {
  await sharp(Buffer.from(candle(size, scale))).png().toFile(new URL(name, OUT))
  console.log(`wrote public/icons/${name}`)
}

await mkdir(OUT, { recursive: true })
await write("icon-192.png", 192, 0.7)
await write("icon-512.png", 512, 0.7)
await write("icon-512-maskable.png", 512, 0.5)
```

- [ ] **Step 6: Generate the icons**

Run: `npm run icons`
Expected: three `wrote public/icons/...` lines. Open `public/icons/icon-512.png` and confirm a mint hollow candle on a near-black square.

- [ ] **Step 7: Run tests to verify they pass**

Run: `npm test`
Expected: PASS, including the on-disk icon check.

- [ ] **Step 8: Check the route serves**

Run: `npm run dev` then `curl -i http://localhost:3000/manifest.webmanifest`
Expected: `200`, `content-type: application/manifest+json`, body matches the object above. Stop the dev server.

- [ ] **Step 9: Commit**

```bash
git add frontend/app/manifest.ts frontend/scripts/make-icons.mjs frontend/public/icons frontend/tests/manifest.test.ts frontend/package.json frontend/package-lock.json
git commit -m "Add a web app manifest and launcher icons

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Offline page and service worker

**Files:**
- Create: `frontend/app/offline/page.tsx`
- Create: `frontend/public/sw.js`
- Create: `frontend/components/register-sw.tsx`
- Create: `frontend/tests/sw.test.ts`
- Modify: `frontend/app/layout.tsx`

**Interfaces:**
- Consumes: `/offline` and `/sw.js` bypass from Task 1.
- Produces: a registered service worker at scope `/` that answers failed navigations with the cached `/offline` page.

- [ ] **Step 1: Write the failing test**

The worker is a plain script that talks to `self`, `caches` and `fetch`. The test fakes those three, imports the file so its listeners register, then drives the `install` and `fetch` handlers directly.

`frontend/tests/sw.test.ts`:
```ts
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
      request: new Request("https://app.vibetrading.club/", { mode: "navigate" } as RequestInit),
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
      request: new Request("https://app.vibetrading.club/", { mode: "navigate" } as RequestInit),
    })
    expect(await (await responded!).text()).toBe("live")
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- sw`
Expected: FAIL — `Cannot find module '../public/sw.js'`.

- [ ] **Step 3: Create `frontend/public/sw.js`**

```js
/*
 * Offline fallback only.
 *
 * A Trusted Web Activity with no network shows Chrome's error page, which is
 * the one screen that makes the app look like a wrapped website. This worker
 * keeps exactly one thing - the /offline page - and hands it back when a
 * navigation cannot reach the server. It never caches API responses or chart
 * assets: a stale candle presented as live would be worse than an error.
 */
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- sw`
Expected: PASS (4 tests).

- [ ] **Step 5: Create `frontend/app/offline/page.tsx`**

Inline styles on purpose: when this page is served from the cache the stylesheet and fonts it would normally load are not available, so it must look right with nothing but its own markup.

```tsx
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
```

- [ ] **Step 6: Create `frontend/components/register-sw.tsx`**

```tsx
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
```

- [ ] **Step 7: Mount it in `frontend/app/layout.tsx`**

Add the import beside the other component imports:
```tsx
import RegisterServiceWorker from '@/components/register-sw'
```
In the body, after `<Analytics />`:
```tsx
        <RegisterServiceWorker />
```

- [ ] **Step 8: Check it end to end in the browser**

Run: `npm run build && npm run start` (the worker only registers against a production build reliably). Open `http://localhost:3000/app` in Chrome → DevTools → Application → Service Workers: `sw.js` is *activated and running*. Tick **Offline**, reload: the "No connection" page appears with the candle mark and mint "Retry" link. Untick, click Retry: the panel loads. Also open `http://localhost:3000/offline` directly and confirm it renders identically with the network on. Stop the server.

- [ ] **Step 9: Run the full suite and commit**

Run: `npm test` → all PASS.
```bash
git add frontend/public/sw.js frontend/app/offline/page.tsx frontend/components/register-sw.tsx frontend/app/layout.tsx frontend/tests/sw.test.ts
git commit -m "Serve an offline page from a service worker

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: WalletConnect connector

**Files:**
- Modify: `frontend/lib/wallet.ts`
- Modify: `frontend/next.config.mjs`
- Modify: `.env.prod.example`
- Create: `frontend/tests/wallet.test.ts`

**Interfaces:**
- Produces: `buildConnectors(projectId: string | undefined): CreateConnectorFn[]` — `[injected]` when no project id, `[injected, walletConnect]` when set. `wagmiConfig` is built from `buildConnectors(process.env.NEXT_PUBLIC_WALLETCONNECT_PROJECT_ID)`.

- [ ] **Step 1: Get a WalletConnect project id (user action, can happen in parallel)**

At https://cloud.reown.com create a project named "VibeTrading", type *AppKit*, and under its settings add `app.vibetrading.club` and `vibetrading.club` as allowed domains. Copy the Project ID. In the Vercel dashboard → the frontend project → Settings → Environment Variables, add `NEXT_PUBLIC_WALLETCONNECT_PROJECT_ID` for Production and Preview. Locally, add the same line to `frontend/.env.local` (gitignored).

- [ ] **Step 2: Install the provider**

Run from `frontend/`:
```bash
npm install @walletconnect/ethereum-provider@^2.21.1
```
(`@wagmi/connectors` 8.2.0 declares it as an optional peer at `^2.21.1`; wagmi loads it lazily when the connector is first used.)

- [ ] **Step 3: Write the failing test**

`frontend/tests/wallet.test.ts`:
```ts
import { describe, expect, it } from "vitest"

import { buildConnectors } from "@/lib/wallet"

describe("buildConnectors", () => {
  it("is injected-only when no WalletConnect project id is configured", () => {
    expect(buildConnectors(undefined)).toHaveLength(1)
    expect(buildConnectors("")).toHaveLength(1)
  })

  it("adds WalletConnect after injected when a project id is set", () => {
    expect(buildConnectors("abc123")).toHaveLength(2)
  })
})
```

- [ ] **Step 4: Run test to verify it fails**

Run: `npm test -- wallet`
Expected: FAIL — `buildConnectors` is not exported.

- [ ] **Step 5: Update `frontend/lib/wallet.ts`**

Replace the file's imports and config with:
```ts
import { createConfig, http, type CreateConnectorFn } from "wagmi"
import { arbitrum } from "wagmi/chains"
// Narrow subpaths, not the "wagmi/connectors" barrel: the barrel re-exports
// every connector including Coinbase and Safe, which would pull their code into
// the bundle for wallets this feature does not offer.
import { injected } from "wagmi/connectors/injected"
import { walletConnect } from "wagmi/connectors/walletConnect"

export const ARBITRUM_CHAIN_ID = arbitrum.id
export const ARBITRUM_NAME = arbitrum.name

/**
 * Injected first, WalletConnect second.
 *
 * Injected covers browser extensions on desktop. WalletConnect is what makes
 * sign-in possible on a phone - Android has no extension wallets, so inside the
 * Play Store app it is the only route to a signature. It is only offered when a
 * project id is configured, so a local build without one still works on desktop.
 */
export function buildConnectors(projectId: string | undefined): CreateConnectorFn[] {
  const connectors: CreateConnectorFn[] = [injected()]
  if (projectId) {
    connectors.push(
      walletConnect({
        projectId,
        showQrModal: true,
        metadata: {
          name: "VibeTrading",
          description: "Liquidity levels and chart patterns for nine crypto pairs.",
          url: "https://app.vibetrading.club",
          icons: ["https://app.vibetrading.club/icons/icon-512.png"],
        },
      }),
    )
  }
  return connectors
}

export const wagmiConfig = createConfig({
  chains: [arbitrum],
  connectors: buildConnectors(process.env.NEXT_PUBLIC_WALLETCONNECT_PROJECT_ID),
  transports: {
    // The default public RPC. Nothing here reads chain state - the address and a
    // signature are all this feature needs - so no paid provider is required.
    [arbitrum.id]: http(),
  },
  // Next.js renders client components on the server too. Without this, wagmi
  // reads persisted state during SSR and the first client render disagrees with
  // the server's HTML.
  ssr: true,
})
```
Keep the existing `shortAddress` export at the bottom unchanged.

- [ ] **Step 6: Run test to verify it passes**

Run: `npm test -- wallet`
Expected: PASS.

- [ ] **Step 7: Silence the optional-dependency warnings in `frontend/next.config.mjs`**

WalletConnect's transitive deps reference `pino-pretty`, `lokijs` and `encoding` behind `require` guards, and webpack reports each as "Module not found". Add inside `nextConfig`:
```js
  // WalletConnect's dependencies probe for these optional modules at runtime;
  // marking them external stops webpack warning about each one on every build.
  webpack: (config) => {
    config.externals.push("pino-pretty", "lokijs", "encoding")
    return config
  },
```

- [ ] **Step 8: Build and check the bundle boundary**

Run: `npm run build`
Expected: succeeds with no "Module not found" warnings. In the route table, the `/app` first-load JS grows (WalletConnect is ~200 KB gzipped); `/` and `/legal/*` must be unchanged — they do not import `lib/wallet.ts`.

- [ ] **Step 9: Document the variable in `.env.prod.example`**

Append:
```
# --- Frontend (set in the Vercel project, not on the VM) ---
# WalletConnect / Reown project id from https://cloud.reown.com. Enables wallet
# sign-in from phones, including the Android app. Without it only browser
# extension wallets are offered.
NEXT_PUBLIC_WALLETCONNECT_PROJECT_ID=
```

- [ ] **Step 10: Commit**

```bash
git add frontend/lib/wallet.ts frontend/next.config.mjs frontend/tests/wallet.test.ts frontend/package.json frontend/package-lock.json .env.prod.example
git commit -m "Offer WalletConnect beside the injected wallet

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: Choose the right connector and say so in the privacy policy

**Files:**
- Modify: `frontend/lib/wallet.ts` (add `pickConnector`)
- Modify: `frontend/hooks/use-session.ts:75-83`
- Modify: `frontend/app/legal/privacy/page.tsx` (wallet section)
- Modify: `frontend/tests/wallet.test.ts`

**Interfaces:**
- Consumes: connector ids `"injected"` and `"walletConnect"` (wagmi's fixed ids for those two connectors).
- Produces: `pickConnector<T extends { id: string }>(connectors: readonly T[], hasInjectedProvider: boolean): T | undefined`.

- [ ] **Step 1: Add the failing tests to `frontend/tests/wallet.test.ts`**

Extend the import and append:
```ts
import { buildConnectors, pickConnector } from "@/lib/wallet"

const injectedC = { id: "injected" }
const wcC = { id: "walletConnect" }

describe("pickConnector", () => {
  it("prefers the injected wallet when the browser has one", () => {
    expect(pickConnector([injectedC, wcC], true)).toBe(injectedC)
  })

  it("falls back to WalletConnect when there is no injected provider", () => {
    expect(pickConnector([injectedC, wcC], false)).toBe(wcC)
  })

  it("never returns the injected connector without a provider to back it", () => {
    expect(pickConnector([injectedC], false)).toBeUndefined()
  })

  it("uses WalletConnect on a browser with a provider if injected is not offered", () => {
    expect(pickConnector([wcC], true)).toBe(wcC)
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npm test -- wallet`
Expected: FAIL — `pickConnector` is not exported.

- [ ] **Step 3: Add `pickConnector` to `frontend/lib/wallet.ts`**

After `buildConnectors`:
```ts
/**
 * The connector to start with when the user clicks "Connect".
 *
 * The injected connector is only useful when there is actually an injected
 * provider - on a phone there is none, and wagmi would report "provider not
 * found" for a button that looked perfectly clickable. So it is chosen only when
 * the page has seen window.ethereum; otherwise WalletConnect, whose modal
 * deep-links to whatever wallet app is installed.
 */
export function pickConnector<T extends { id: string }>(
  connectors: readonly T[],
  hasInjectedProvider: boolean,
): T | undefined {
  const byId = (id: string) => connectors.find((c) => c.id === id)
  return (hasInjectedProvider ? byId("injected") : undefined) ?? byId("walletConnect")
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npm test -- wallet`
Expected: PASS (6 tests).

- [ ] **Step 5: Use it in `frontend/hooks/use-session.ts`**

Change the import:
```ts
import { ARBITRUM_CHAIN_ID, pickConnector } from "@/lib/wallet"
```
Replace `startConnect`:
```ts
  const startConnect = useCallback(() => {
    setError(null)
    const hasInjectedProvider =
      typeof window !== "undefined" && Boolean((window as { ethereum?: unknown }).ethereum)
    const connector = pickConnector(connectors, hasInjectedProvider)
    if (!connector) {
      setError(
        "No wallet found. On a computer, install MetaMask or Rabby. On a phone, open this page from inside your wallet app's browser.",
      )
      return
    }
    connect({ connector })
  }, [connect, connectors])
```

- [ ] **Step 6: Add the WalletConnect sentence to `frontend/app/legal/privacy/page.tsx`**

In the "Your wallet address, if you build strategy rules" section, after the paragraph ending "…authorises no transaction or spending.", insert:
```tsx
      <p>
        If you connect from a phone, the connection is relayed through
        WalletConnect&rsquo;s servers, which see your wallet address and this
        app&rsquo;s name in order to pair the two. The signature request itself
        goes to your wallet, not to them.
      </p>
```

- [ ] **Step 7: Verify by hand on desktop and on a phone**

Desktop Chrome with MetaMask, `npm run dev`, open `/app` → Strategy → Connect wallet: MetaMask opens directly, no WalletConnect modal. Then Chrome with extensions disabled (or a guest profile): Connect wallet → WalletConnect QR modal appears; scan with MetaMask mobile → address connects → Sign in → signature prompt on the phone → rules panel unlocks.

Phone (mobile Chrome, same Wi-Fi, `http://<your-lan-ip>:3000/app`; wagmi needs a secure context for some wallets, so if the modal fails to appear use the Vercel preview URL after pushing instead): Connect wallet → modal lists installed wallets → tap MetaMask → approve → return to Chrome → Sign in → approve → rules panel.

- [ ] **Step 8: Run the suite and commit**

Run: `npm test` → all PASS. `npm run build` → succeeds.
```bash
git add frontend/lib/wallet.ts frontend/hooks/use-session.ts frontend/app/legal/privacy/page.tsx frontend/tests/wallet.test.ts
git commit -m "Pick WalletConnect when the browser has no injected wallet

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: Deploy checkpoint and Bubblewrap project

Bubblewrap reads the manifest from the live origin, so Tasks 1–5 must be on `app.vibetrading.club` first.

**Files:**
- Create: `android/` (generated), `android/twa-manifest.json` (edited)
- Modify: `.gitignore`

**Interfaces:**
- Produces: `android/app-release-signed.apk` (sideload) and `android/app-release-bundle.aab` (Play), plus the upload key's SHA-256 fingerprint used in Task 7.

- [ ] **Step 1: Push and confirm the live origin serves the PWA files**

```bash
git push origin main
```
Wait for the Vercel deployment to finish, then:
```bash
curl -sI https://app.vibetrading.club/manifest.webmanifest | grep -i "content-type"
curl -sI https://app.vibetrading.club/sw.js | grep -i "content-type"
curl -s https://app.vibetrading.club/offline | grep -c "No connection"
```
Expected: `application/manifest+json`, `application/javascript` (or `text/javascript`), and `1`. If any of these returns `text/html` with the panel, the middleware bypass is not live yet.

Then Chrome → `https://app.vibetrading.club` → DevTools → Lighthouse → *Progressive Web App* category only → Analyze. Expected: "Installable" passes, manifest has no errors, service worker registered.

- [ ] **Step 2: Install Bubblewrap**

```bash
npm install -g @bubblewrap/cli
bubblewrap doctor
```
On first run Bubblewrap asks to install JDK 17 and the Android command-line tools under `~/.bubblewrap/`; answer **Y** to both. `doctor` should then report both paths valid.

- [ ] **Step 3: Create the keys directory outside the repo**

```powershell
New-Item -ItemType Directory -Force D:\smartTradeAI\keys
```

- [ ] **Step 4: Generate the Android project**

From the repo root:
```bash
bubblewrap init --manifest https://app.vibetrading.club/manifest.webmanifest --directory android
```
Answer the prompts:

| Prompt | Answer |
|---|---|
| Domain | `app.vibetrading.club` |
| URL path | `/` |
| Application name | `VibeTrading` |
| Short name | `VibeTrading` |
| Application ID | `club.vibetrading.app` |
| Starting version code | `1` |
| Display mode | `standalone` |
| Status bar colour | `#040609` |
| Splash screen colour | `#040609` |
| Icon URL | accept the default (`…/icons/icon-512.png`) |
| Maskable icon URL | `https://app.vibetrading.club/icons/icon-512-maskable.png` |
| Include support for Play Billing | `No` |
| Request geolocation permission | `No` |
| Key store location | `D:\smartTradeAI\keys\vibetrading-upload.keystore` |
| Key name (alias) | `android` |
| Create the key store now | `Yes` → set a password, store it in your password manager, fill in name/org/country |

- [ ] **Step 5: Lock orientation and disable notifications in `android/twa-manifest.json`**

Edit the generated file so these keys read:
```json
  "orientation": "portrait",
  "enableNotifications": false,
  "fallbackType": "customtabs",
```
(`fallbackType: customtabs` is what runs on a phone without Chrome — it shows a URL bar there, but works.) Then regenerate the project from the manifest:
```bash
cd android && bubblewrap update && cd ..
```

- [ ] **Step 6: Ignore build outputs and keys in `.gitignore`**

Append to the repo root `.gitignore`:
```
# --- Android (Bubblewrap) ---
android/app/build/
android/build/
android/.gradle/
android/local.properties
android/*.apk
android/*.aab
android/*.idsig
*.keystore
*.jks
```

- [ ] **Step 7: Build**

```bash
cd android && bubblewrap build
```
Enter the keystore and key passwords when prompted. Expected output ends with `app-release-signed.apk` and `app-release-bundle.aab` in `android/`, and Bubblewrap prints the signing key's SHA-256 and writes an `assetlinks.json` beside them. Copy the SHA-256 line — Task 7 needs it. If you missed it:
```bash
keytool -list -v -keystore D:\smartTradeAI\keys\vibetrading-upload.keystore -alias android | findstr SHA256
```

- [ ] **Step 8: Sideload and smoke-test**

Enable USB debugging on an Android phone, connect it, then:
```bash
adb install android/app-release-signed.apk
```
(`adb` is under `~/.bubblewrap/android_sdk/platform-tools/`.) Launch VibeTrading. Expected at this stage: splash in `#040609` with the candle, then the panel **with a URL bar** (asset links are not published yet — that is Task 7), portrait locked when you rotate, and airplane mode → the offline page.

- [ ] **Step 9: Commit the project**

```bash
git add .gitignore android/
git status --short android | grep -i "keystore\|\.aab\|\.apk"
```
The grep must print nothing. Then:
```bash
git commit -m "Add the Android Trusted Web Activity project

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 7: Digital Asset Links

**Files:**
- Create: `frontend/public/.well-known/assetlinks.json`
- Create: `frontend/tests/assetlinks.test.ts`
- Modify: `README.md`

**Interfaces:**
- Consumes: the upload key SHA-256 from Task 6 step 7; `.well-known/` bypass from Task 1.
- Produces: `https://app.vibetrading.club/.well-known/assetlinks.json`. Task 8 adds a second fingerprint to it.

- [ ] **Step 1: Write the failing test**

`frontend/tests/assetlinks.test.ts`:
```ts
import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"

const file = fileURLToPath(new URL("../public/.well-known/assetlinks.json", import.meta.url))

describe("Digital Asset Links", () => {
  const statements = JSON.parse(readFileSync(file, "utf8")) as Array<{
    relation: string[]
    target: { namespace: string; package_name: string; sha256_cert_fingerprints: string[] }
  }>

  it("delegates URL handling to the Android app", () => {
    expect(statements).toHaveLength(1)
    expect(statements[0].relation).toEqual(["delegate_permission/common.handle_all_urls"])
    expect(statements[0].target.namespace).toBe("android_app")
    expect(statements[0].target.package_name).toBe("club.vibetrading.app")
  })

  it("lists only well-formed SHA-256 fingerprints", () => {
    const prints = statements[0].target.sha256_cert_fingerprints
    expect(prints.length).toBeGreaterThanOrEqual(1)
    for (const p of prints) expect(p).toMatch(/^([0-9A-F]{2}:){31}[0-9A-F]{2}$/)
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- assetlinks`
Expected: FAIL — `ENOENT … assetlinks.json`.

- [ ] **Step 3: Generate the file from the Android project**

From `android/`:
```bash
bubblewrap fingerprint list
```
Expected: the upload key's SHA-256 is listed (added by `build`). If the list is empty, add it with the value from Task 6 step 7:
```bash
bubblewrap fingerprint add <SHA256-with-colons>
```
Then write the statement file into the frontend:
```bash
bubblewrap fingerprint generateAssetLinks --output ../frontend/public/.well-known/assetlinks.json
```
Open it; it should read (fingerprint will differ):
```json
[{
  "relation": ["delegate_permission/common.handle_all_urls"],
  "target": {
    "namespace": "android_app",
    "package_name": "club.vibetrading.app",
    "sha256_cert_fingerprints": ["AB:CD:…:EF"]
  }
}]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- assetlinks`
Expected: PASS.

- [ ] **Step 5: Add an Android section to `README.md`**

Under "Project layout", add `android/           Trusted Web Activity project (Bubblewrap); twa-manifest.json is the source of truth` and `store/             Play Store listing assets`. Under "Running it locally", after the Tests subsection, add:

````markdown
### Android app

The Play Store app is a Trusted Web Activity: Chrome rendering
`app.vibetrading.club` full-screen. Nothing is duplicated; a deploy to Vercel
updates the app.

```bash
npm install -g @bubblewrap/cli
cd android
bubblewrap build          # asks for the upload keystore password
adb install app-release-signed.apk
```

Bump `appVersionCode` in `android/twa-manifest.json` and run `bubblewrap update`
before each upload to Play. `frontend/public/.well-known/assetlinks.json` must
list both the upload key and the Play App Signing key, or Chrome shows a URL
bar. Frontend unit tests: `cd frontend && npm test`.
````

- [ ] **Step 6: Deploy and verify**

```bash
git add frontend/public/.well-known/assetlinks.json frontend/tests/assetlinks.test.ts README.md
git commit -m "Publish Digital Asset Links for the Android app

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
git push origin main
```
After Vercel deploys:
```bash
curl -si https://app.vibetrading.club/.well-known/assetlinks.json | grep -i "content-type\|package_name"
```
Expected: `content-type: application/json` and the package name. Then Google's verifier:
```
https://digitalassetlinks.googleapis.com/v1/statements:list?source.web.site=https://app.vibetrading.club&relation=delegate_permission/common.handle_all_urls
```
Expected: a JSON response whose `statements` contains the package and fingerprint, and `"maxAge"` — not an error.

- [ ] **Step 7: Confirm the URL bar is gone**

On the phone: Settings → Apps → Chrome → Storage → Clear cache (Chrome caches a failed verification), then reopen VibeTrading. Expected: no URL bar, panel fills the screen edge to edge.

---

### Task 8: Play Console — app record, internal testing, Play signing fingerprint

No code beyond one regenerated JSON. The point of uploading to Internal testing first is that Play only reveals its App Signing certificate after the first upload, and Chrome will show a URL bar on every store-installed copy until that certificate is in `assetlinks.json`.

**Files:**
- Modify: `frontend/public/.well-known/assetlinks.json` (second fingerprint)
- Modify: `android/twa-manifest.json` (fingerprint recorded by Bubblewrap)

- [ ] **Step 1: Create the app**

https://play.google.com/console → *Create app*: name `VibeTrading`, default language English (United States), App, Free. Accept the declarations.

- [ ] **Step 2: Upload to Internal testing**

Testing → Internal testing → *Create new release*. When asked about signing, choose **Use Google-generated key** (Play App Signing). Upload `android/app-release-bundle.aab`. Release name `1 (1.0.0)`, notes "First internal build." → Save → Review release → Start rollout. Add your own Google account under *Testers* and install from the opt-in link to confirm it launches.

- [ ] **Step 3: Copy the Play App Signing fingerprint**

Test and release → Setup → *App signing* → **App signing key certificate** → SHA-256 certificate fingerprint. Copy it (with colons).

- [ ] **Step 4: Add it to the asset links**

From `android/`:
```bash
bubblewrap fingerprint add <PLAY-SHA256>
bubblewrap fingerprint generateAssetLinks --output ../frontend/public/.well-known/assetlinks.json
cd ../frontend && npm test -- assetlinks
```
Expected: the file now lists two fingerprints; test PASS.

- [ ] **Step 5: Commit, deploy, verify**

```bash
git add frontend/public/.well-known/assetlinks.json android/twa-manifest.json
git commit -m "Trust the Play App Signing key in the asset links

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
git push origin main
```
After deploy, re-run the statements:list URL from Task 7 step 6 and confirm both fingerprints appear. Uninstall the sideloaded app on the phone, install from the Internal testing link, clear Chrome's cache, open: no URL bar.

- [ ] **Step 6: Read the pre-launch report**

Testing → Pre-launch report (appears a few hours after rollout). Expected: crawls on several devices, screenshots show the panel without a URL bar, no crashes. A screenshot with a URL bar means a device tested before the asset links propagated — re-upload a build (bump `appVersionCode` to 2, `bubblewrap update`, `bubblewrap build`) and check again.

---

### Task 9: Store listing and app-content declarations

**Files:**
- Create: `store/make-feature-graphic.mjs`, `store/feature-graphic.png`, `store/screenshots/*.png`, `store/listing.md`

- [ ] **Step 1: Render the feature graphic**

`store/make-feature-graphic.mjs` (run with `node store/make-feature-graphic.mjs` from the repo root; uses the frontend's sharp):
```js
import { createRequire } from "node:module"
const sharp = createRequire(new URL("../frontend/package.json", import.meta.url))("sharp")

const BG = "#040609"
const INK = "#7af0ce"
const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="500" viewBox="0 0 1024 500">
  <rect width="1024" height="500" fill="${BG}"/>
  <g transform="translate(300 122) scale(8)" stroke="${INK}" stroke-width="3">
    <line x1="16" y1="3" x2="16" y2="29"/>
    <rect x="9.5" y="11" width="13" height="10" fill="${BG}"/>
  </g>
  <text x="600" y="235" fill="#f7f7fa" font-family="Arial, Helvetica, sans-serif" font-size="72" font-weight="700" text-anchor="middle">VibeTrading</text>
  <text x="600" y="290" fill="#9aa0ad" font-family="Arial, Helvetica, sans-serif" font-size="28" text-anchor="middle">Levels and patterns, scoped to your chart</text>
</svg>`

await sharp(Buffer.from(svg)).png().toFile(new URL("./feature-graphic.png", import.meta.url))
console.log("wrote store/feature-graphic.png")
```
Open the PNG: 1024×500, candle left of centre, title and strap line legible.

- [ ] **Step 2: Capture phone screenshots**

Chrome → `https://app.vibetrading.club` → DevTools → device toolbar → *Edit* → add a device 1080×2400, DPR 1 → select it. Capture (DevTools ⋮ → *Capture screenshot*) three states and save them as `store/screenshots/01-chart.png`, `02-analysis.png`, `03-assistant.png`: the chart with levels drawn, the Analysis region open, the Assistant region open with an answer. Play requires 2–8 phone screenshots, each 320–3840 px on a side, 16:9 to 9:16.

- [ ] **Step 3: Write `store/listing.md` and paste it into Play Console → Store presence → Main store listing**

```markdown
# Play Store listing copy

**App name:** VibeTrading

**Short description (≤80):**
Liquidity levels and chart patterns, scoped to the candles on your screen.

**Full description:**
VibeTrading reads the candles you are looking at — nine crypto pairs, any timeframe — and draws two things on the chart: the price levels the market keeps returning to, and the double bottoms and double tops forming around them.

Every level shows how many times it has been tested, so strength is measured rather than asserted. Every pattern is marked with where it is in its life — forming, approaching the neckline, or confirmed by a close beyond it — so you see a setup while it develops, not after it has given up its move.

Analysis is scoped to the visible window. Pan or zoom and the chart re-analyses exactly what is on screen.

Two controls, because these are judgement calls: Scale picks the size of structure to look for (swing, scalp or both); Strictness sets the quality bar.

A chat assistant answers questions about the levels and patterns in plain language. It never computes a level or a pattern — the detector is deterministic and every confidence score decomposes into three measurable terms.

Optionally, connect a wallet to build strategy rules that alert you when a pattern or level condition is met. One signature, no transactions, no funds held.

No signup. Free to use.

VibeTrading is not financial advice. It places no trades and holds no funds. A pattern is evidence of a shape, not evidence of an edge.

**Category:** Finance
**Tags:** Cryptocurrency, Technical analysis
**Contact email:** dev@vibetrading.club
**Website:** https://vibetrading.club
**Privacy policy:** https://vibetrading.club/legal/privacy
```

Upload `frontend/public/icons/icon-512.png` as the app icon, `store/feature-graphic.png`, and the three screenshots.

- [ ] **Step 4: Complete *App content* (Policy → App content)**

| Section | Answer |
|---|---|
| Privacy policy | `https://vibetrading.club/legal/privacy` |
| Ads | No, does not contain ads |
| App access | All functionality available without special access (the wallet gate is optional and any wallet works) |
| Content rating | Start questionnaire → category *Utility, Productivity, Communication, or Other* → all No (no violence, no sexual content, no gambling, no real-money gambling, no controlled substances, no user-generated content shared with others) → Save → expect *Everyone* / PEGI 3 |
| Target audience | 18 and over only. Not designed for children. |
| News app | No |
| COVID-19 | No |
| Data safety | See step 5 |
| Government apps | No |
| Financial features | See step 6 |
| Health | No health features |

- [ ] **Step 5: Data safety form**

*Does your app collect or share any of the required user data types?* **Yes.**
*Is all user data encrypted in transit?* **Yes.**
*Do you provide a way for users to request deletion?* **Yes** — URL `https://vibetrading.club/legal/privacy` (the page names dev@vibetrading.club for deletion).

Data types:
- **Personal info → User IDs**: collected, not shared, optional (only when building strategy rules), purpose *App functionality*, not processed ephemerally. (This is the wallet address.)
- **Messages → Other in-app messages**: collected, **shared** (sent to a third-party language-model provider to answer), optional, purpose *App functionality*, processed ephemerally.
- Everything else (location, financial info, contacts, device IDs, crash logs beyond what Play collects itself): not collected.

- [ ] **Step 6: Financial features declaration**

*Does your app provide any financial features?* Select **"My app doesn't provide any financial features"**. Justification if a free-text box is offered: "VibeTrading is a chart-analysis tool. It holds no funds, executes no trades, is not an exchange or a wallet, and connects to no bank or card. A crypto wallet may optionally sign a message to identify the user; no transaction is requested. Risk disclosure: https://vibetrading.club/legal/risk".

- [ ] **Step 7: Store settings**

Store presence → Store settings: App category *Finance*, store listing contact details filled, external marketing on.

- [ ] **Step 8: Commit the assets**

```bash
git add store/
git commit -m "Add Play Store listing assets

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 10: Closed testing and production

- [ ] **Step 1: Create the closed test**

Testing → Closed testing → *Create track* named `Alpha` → *Create new release* → *Add from library* → pick the bundle already uploaded in Task 8 (or a newer one). Testers tab → *Create email list* `vibetrading-testers` → paste at least **12** Google account addresses → save → Feedback URL `mailto:dev@vibetrading.club`. Review and roll out.

- [ ] **Step 2: Send the opt-in link**

Copy the link from the Testers tab (form `https://play.google.com/apps/testing/club.vibetrading.app`). Each tester opens it, taps *Become a tester*, then installs from Play. Ask them to keep the app installed and not to leave the program for **14 days** — the clock counts continuous days with 12 opted in, and drops reset it.

- [ ] **Step 3: While the test runs**

Any code change that goes to Vercel reaches testers immediately (the app is the website). Only a change to `twa-manifest.json` (colours, orientation, version) needs a new bundle: bump `appVersionCode`, `bubblewrap update`, `bubblewrap build`, upload to the Alpha track.

- [ ] **Step 4: Apply for production access**

After 14 days the Dashboard shows *Apply for production*. The form asks about the test: state that testers were recruited personally, feedback was collected by email, and describe one change made in response (e.g. copy on the offline page). Submit. Google typically answers within 7 days.

- [ ] **Step 5: Roll out to production**

Once granted: Production → *Create new release* → add the same bundle from the library → release notes "Initial release." → Review → Start rollout to 100%. Review takes from hours to a few days. When the listing goes live, add the Play badge and link to the landing page's footer in a separate change.

---

## Self-review

**Spec coverage.** §1 manifest → Task 2; icons → Task 2; service worker + offline → Task 3; asset links (upload then Play key) → Tasks 7–8; middleware → Task 1. §2 WalletConnect connector + env → Task 4; connector selection + error copy + privacy sentence → Task 5. §3 Android shell, settings, gitignore, keystore outside repo, build → Task 6. §4 Play Console steps 1–6 → Tasks 8–10 in the spec's order. §5 testing: Lighthouse and curl checks → Task 6 step 1 and Task 7 step 6; `bubblewrap doctor` → Task 6 step 2; sideload checks → Task 6 step 8 and Task 7 step 7; desktop-unchanged wallet check → Task 5 step 7; backend untouched → no task modifies `backend/`.

**Placeholders.** The `<SHA256…>` and `<PLAY-SHA256>` tokens are runtime values produced by earlier steps, with the command that produces each. No TBD/TODO.

**Type consistency.** `isPwaPath(pathname: string): boolean` (Task 1) is what `middleware.ts` calls. `buildConnectors` and `pickConnector` are defined in Task 4/5 with the signatures `use-session.ts` uses. Connector ids `"injected"` / `"walletConnect"` match wagmi's connector ids. Colours `#040609` / `#7af0ce` are the same in the manifest, icon script, offline page, twa-manifest prompts and feature graphic.
