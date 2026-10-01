import Link from "next/link"
import Wordmark from "@/components/wordmark"
import { CONTACT_EMAIL } from "@/lib/contact"

/*
 * Shared chrome for the three legal pages. They are plain prose on the same
 * dark surface as the rest of the site - a reader checking whether this is a
 * serious operation should not land on something that looks bolted on.
 */

const PAGES = [
  { href: "/legal/risk", label: "Risk disclosure" },
  { href: "/legal/terms", label: "Terms of use" },
  { href: "/legal/privacy", label: "Privacy" },
]

export default function LegalLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen" style={{ background: "var(--vt-void)" }}>
      <header
        className="border-b"
        style={{ borderColor: "var(--vt-line)" }}
      >
        <div className="mx-auto flex max-w-3xl items-center justify-between px-6 py-5">
          <Link href="/" aria-label="VibeTrading home">
            <Wordmark />
          </Link>
          <Link
            href="/app"
            className="font-mono text-[11px] transition-colors hover:opacity-80"
            style={{ color: "var(--vt-mint)" }}
          >
            Open the chart →
          </Link>
        </div>
      </header>

      <main className="mx-auto max-w-3xl px-6 py-12">
        <nav className="mb-10 flex flex-wrap gap-x-5 gap-y-2">
          {PAGES.map((p) => (
            <Link
              key={p.href}
              href={p.href}
              className="font-mono text-[11px] uppercase tracking-wide transition-colors hover:opacity-80"
              style={{ color: "var(--vt-ink-dim)" }}
            >
              {p.label}
            </Link>
          ))}
        </nav>

        <article className="legal-prose" style={{ color: "var(--vt-ink-dim)" }}>
          {children}
        </article>

        <div
          className="mt-14 border-t pt-6"
          style={{ borderColor: "var(--vt-line)" }}
        >
          <p className="text-sm" style={{ color: "var(--vt-ink-dim)" }}>
            Questions about anything on this page? Write to{" "}
            <a
              href={`mailto:${CONTACT_EMAIL}`}
              className="underline underline-offset-4"
              style={{ color: "var(--vt-mint)" }}
            >
              {CONTACT_EMAIL}
            </a>
            . A real person reads it.
          </p>
        </div>
      </main>
    </div>
  )
}
