import { describe, expect, it } from "vitest"

import { shouldRegisterServiceWorker } from "@/components/register-sw"

describe("shouldRegisterServiceWorker", () => {
  it.each(["app.vibetrading.club", "localhost"])("registers on %s", (host) => {
    expect(shouldRegisterServiceWorker(host)).toBe(true)
  })

  it.each(["vibetrading.club", "www.vibetrading.club", "app-preview.vercel.app"])(
    "does not register on %s",
    (host) => {
      expect(shouldRegisterServiceWorker(host)).toBe(false)
    },
  )
})
