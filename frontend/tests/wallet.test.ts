import { describe, expect, it } from "vitest"

import { buildConnectors, pickConnector } from "@/lib/wallet"

describe("buildConnectors", () => {
  it("is injected-only when no WalletConnect project id is configured", () => {
    expect(buildConnectors(undefined)).toHaveLength(1)
    expect(buildConnectors("")).toHaveLength(1)
  })

  it("adds WalletConnect after injected when a project id is set", () => {
    expect(buildConnectors("abc123")).toHaveLength(2)
  })
})

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
