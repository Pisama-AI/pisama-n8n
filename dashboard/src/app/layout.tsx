import type { Metadata } from 'next'
import { Inter_Tight, Newsreader, JetBrains_Mono } from 'next/font/google'
import './globals.css'
import { Providers } from './providers'

// Same three faces as the Pisama monorepo frontend (editorial / broadsheet).
const interTight = Inter_Tight({
  subsets: ['latin'],
  weight: ['400', '500', '600', '700'],
  variable: '--font-ui',
  display: 'swap',
})
const newsreader = Newsreader({
  subsets: ['latin'],
  style: ['normal', 'italic'],
  variable: '--font-serif',
  display: 'swap',
  preload: false,
})
const jetbrainsMono = JetBrains_Mono({
  subsets: ['latin'],
  variable: '--font-jetbrains',
  display: 'swap',
  preload: false,
})

export const metadata: Metadata = {
  title: 'Pisama · n8n',
  description: 'Self-hosted failure detection for n8n workflows.',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body
        className={`${interTight.variable} ${newsreader.variable} ${jetbrainsMono.variable} font-sans`}
      >
        <a href="#main-content" className="skip-link">
          Skip to content
        </a>
        <Providers>
          <div id="main-content">{children}</div>
        </Providers>
      </body>
    </html>
  )
}
