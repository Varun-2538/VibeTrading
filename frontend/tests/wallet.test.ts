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
