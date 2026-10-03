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

  it("declares an explicit scope and id", () => {
    // Left to inference, engines disagree about what counts as leaving the
    // app - and a departure is what makes the Android app show the browser's
    // close button and URL bar over itself.
    expect(m.scope).toBe("/")
    expect(m.id).toBe("/")
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
