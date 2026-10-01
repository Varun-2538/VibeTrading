import { NextResponse } from "next/server"
import type { NextRequest } from "next/server"

/**
 * One deployment serves two hosts:
 *   vibetrading.club      -> the landing page
 *   app.vibetrading.club  -> the trading panel
 *
 * The panel lives at /app in the route tree. On the app subdomain we rewrite
 * the root onto it so the URL stays clean, and send /app back to the bare
 * path so the same page is never reachable at two URLs.
 */
export function middleware(request: NextRequest) {
  const host = request.headers.get("host") ?? ""
  const isAppHost = host.split(":")[0].startsWith("app.")
  const { pathname } = request.nextUrl

  if (!isAppHost) return NextResponse.next()

  if (pathname === "/app" || pathname.startsWith("/app/")) {
    const url = request.nextUrl.clone()
    url.pathname = pathname.slice(4) || "/"
    return NextResponse.redirect(url)
  }

  const url = request.nextUrl.clone()
  url.pathname = `/app${pathname === "/" ? "" : pathname}`
  return NextResponse.rewrite(url)
}

export const config = {
  // Skip static assets and the API namespace.
  matcher: ["/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico)$).*)"],
}
