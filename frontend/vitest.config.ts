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
