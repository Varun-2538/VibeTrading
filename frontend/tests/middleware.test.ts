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
