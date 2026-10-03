import type { Metadata, Viewport } from 'next'
import { GeistSans } from 'geist/font/sans'
import { GeistMono } from 'geist/font/mono'
import { Archivo } from 'next/font/google'
import { Analytics } from '@vercel/analytics/next'
import './globals.css'

// Display face: a wide, confident grotesk. Deliberately not the body face -
// headlines should not read as large body copy.
const archivo = Archivo({
  subsets: ['latin'],
  weight: ['700', '800'],
  variable: '--font-display',
  display: 'swap',
})

export const metadata: Metadata = {
  title: 'VibeTrading — Find the levels that actually hold',
  description:
    'VibeTrading reads the last 100 hours of candles, clusters the prices the market keeps returning to, and marks them on your chart with the number of times each was tested.',
  metadataBase: new URL('https://vibetrading.club'),
  openGraph: {
    title: 'VibeTrading — Find the levels that actually hold',
    description:
      'Ask where liquidity is sitting. Get support, resistance and a strategy in seconds.',
    url: 'https://vibetrading.club',
    siteName: 'VibeTrading',
    type: 'website',
  },
}

// The trading panel runs edge to edge and puts its region switcher against
// the bottom of the screen, so it needs the safe-area insets to resolve to
// something other than zero. Zoom is left alone deliberately.
export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  viewportFit: 'cover',
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html lang="en">
      <body
        className={`font-sans ${GeistSans.variable} ${GeistMono.variable} ${archivo.variable}`}
      >
        {children}
        <Analytics />
      </body>
    </html>
  )
}
