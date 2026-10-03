import { describe, expect, it } from "vitest"

import { isPwaPath } from "@/lib/pwa-paths"

describe("isPwaPath", () => {
  it.each([
    "/manifest.webmanifest",
    "/sw.js",
    "/offline",
    "/.well-known/assetlinks.json",
    // Linked from inside the panel; must stay on the app origin so the
    // Android app never shows the browser's own chrome over itself.
    "/legal/privacy",
    "/legal/risk",
    "/architecture",
  ])("passes %s through untouched", (path) => {
    expect(isPwaPath(path)).toBe(true)
  })

  it.each(["/", "/app", "/offline-chart", "/wellknown", "/legalese", "/architectures"])(
    "still rewrites %s",
    (path) => {
      expect(isPwaPath(path)).toBe(false)
    },
  )
})
