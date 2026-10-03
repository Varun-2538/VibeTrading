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
