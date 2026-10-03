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
