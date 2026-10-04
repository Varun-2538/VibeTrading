import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"

import { disclosureText } from "@/lib/vault"

const root = join(__dirname, "..")
const repo = join(root, "..")

/**
 * Collapse whitespace before matching. A claim is a claim however it is wrapped, and
 * the first version of this file asserted line breaks - so a formatter reflowing a
 * paragraph broke a test about what the page promises.
 */
const read = (path: string) => readFileSync(join(root, path), "utf8").replace(/\s+/g, " ")

const risk = read("app/legal/risk/page.tsx")
const terms = read("app/legal/terms/page.tsx")
const privacy = read("app/legal/privacy/page.tsx")
const landing = read("app/page.tsx")
const architecture = read("app/architecture/page.tsx")

/**
 * The legal copy is not decoration: the terms incorporate the risk page by reference,
 * and the Play declaration repeats it. So the claims are asserted here, in both
 * directions — the ones that stopped being true must be gone, and the ones that are
 * still true and load-bearing must still be on the page.
 */
describe("claims that stopped being true", () => {
  it("no longer says we execute nothing", () => {
    for (const page of [risk, terms, privacy, landing]) {
      expect(page).not.toContain("We do not execute trades")
      expect(page).not.toContain("no order placement")
      expect(page).not.toContain("places no trades")
      expect(page).not.toContain("Alerts only")
      expect(page).not.toContain("executes no trades")
    }
  })

  it("scopes the wallet-signature promise to alerts, and names the separate grant", () => {
    // Signing in still authorises nothing, and the pages should still say so - what
    // changed is that a separate, explicit grant now exists beside it. So the test is
    // that the old claim is qualified rather than deleted: an unqualified "we could
    // never move anything" would be the false version.
    expect(risk).toContain("for alerts that is all it does")
    expect(risk).toContain("Execution is a separate, explicit step")
    expect(privacy).toContain("never part of signing in")
    expect(privacy).not.toContain("we cannot move anything, and signing in authorises no")
  })
})

describe("promises that are still true, and are the reason this is safe", () => {
  it("keeps the four that matter, in the words the contract enforces", () => {
    expect(risk).toContain("We do not hold your funds")
    expect(risk).toContain("cannot withdraw from it")
    expect(risk).toContain("We cannot move a stop once it is set")
    expect(risk).toContain("revoke it in one transaction")
  })

  it("says the two things people get wrong about a stop", () => {
    // That it is not a fill price, and that this one does not depend on our uptime.
    expect(risk).toContain("A stop is not a fill price")
    expect(risk).toContain("Your stop does not depend on us")
  })

  it("tells people to measure before they spend", () => {
    expect(risk).toContain("Start in shadow mode")
    expect(risk).toContain("unaudited")
  })

  it("still refuses to give advice or take discretion", () => {
    expect(risk).toContain("not investment advice")
    expect(risk).toContain("We do not choose what to trade")
  })

  it("terms still incorporate the risk page, and now cover execution", () => {
    expect(terms).toContain("part of these terms")
    expect(terms).toContain("If you use execution")
    expect(terms).toContain("not a broker")
  })
})

describe("the site and the contract must not contradict each other", () => {
  it("agrees with the text a vault owner signs on chain", () => {
    // The disclosure's hash is stored in the vault forever. If the risk page said
    // something looser than the thing someone accepted, the accepted text would be
    // the one that counted - and we would be the ones out of step.
    const signed = disclosureText()
    expect(signed).toContain("cannot withdraw")
    expect(risk).toContain("cannot withdraw from it")

    expect(signed).toContain("revoke")
    expect(risk).toContain("revoke")

    expect(signed).toContain("not guaranteed fill prices")
    expect(risk).toContain("A stop is not a fill price")
  })
})

describe("the architecture page counts what is actually deployed", () => {
  it("names as many containers as the compose file defines", () => {
    const compose = readFileSync(join(repo, "docker-compose.prod.yml"), "utf8")
    // Top-level keys under services:, which is every container on the machine.
    const services = compose
      .split(/^services:/m)[1]
      .split(/^[a-z]/m)[0]
      .split("\n")
      .filter((line) => /^ {2}[a-z][a-z0-9_-]*:\s*$/.test(line))
    expect(services.length).toBeGreaterThan(0)
    const words = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight"]
    expect(architecture).toContain(`${words[services.length]} containers`)
  })
})
