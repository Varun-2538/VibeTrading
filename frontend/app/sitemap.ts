import type { MetadataRoute } from "next"

const BASE = "https://vibetrading.club"

export default function sitemap(): MetadataRoute.Sitemap {
  const updated = new Date("2026-08-12")
  return [
    { url: BASE, lastModified: updated, priority: 1 },
    { url: `${BASE}/app`, lastModified: updated, priority: 0.8 },
    { url: `${BASE}/legal/risk`, lastModified: updated, priority: 0.5 },
    { url: `${BASE}/legal/terms`, lastModified: updated, priority: 0.4 },
    { url: `${BASE}/legal/privacy`, lastModified: updated, priority: 0.4 },
  ]
}
