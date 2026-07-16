// NextAuth options for SaaS mode — ported from the pisama monorepo's
// frontend/src/lib/auth.ts (Google provider + backend token exchange + JWT
// session strategy). Differences from the monorepo: Google-only (no credentials
// provider), open signup (no ALLOWED_EMAILS gate), and the exchange endpoint
// takes {id_token} as JSON.
import type { NextAuthOptions, Session } from 'next-auth'
import type { JWT } from 'next-auth/jwt'
import GoogleProvider from 'next-auth/providers/google'

// Server-side env (NOT NEXT_PUBLIC): the SaaS API origin the BFF talks to.
export const SAAS_API_URL = process.env.SAAS_API_URL || 'http://localhost:8500'

// The backend JWT lives 24h; treat it as ours for 23 and re-mint inside the
// final hour so upstream never sees a stale bearer.
export const BACKEND_TOKEN_TTL_MS = 23 * 60 * 60 * 1000
export const BACKEND_REFRESH_MARGIN_MS = 60 * 60 * 1000

export interface RefreshedBackendToken {
  accessToken: string
  tenantId: string
}

/** Exchange the current backend bearer (valid, or expired within the server's
 * 7-day grace window) for a fresh 24h one. Server-side only. Returns null on
 * any failure — callers keep the old token and the next request retries. */
export async function refreshBackendToken(bearer: string): Promise<RefreshedBackendToken | null> {
  const ctrl = new AbortController()
  const t = setTimeout(() => ctrl.abort(), 5000)
  try {
    const res = await fetch(`${SAAS_API_URL}/api/v1/auth/refresh`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${bearer}` },
      signal: ctrl.signal,
      cache: 'no-store',
    })
    if (!res.ok) return null
    const data = await res.json()
    if (!data.access_token || !data.tenant_id) return null
    return { accessToken: data.access_token, tenantId: data.tenant_id }
  } catch {
    return null
  } finally {
    clearTimeout(t)
  }
}

export const authOptions: NextAuthOptions = {
  providers: [
    GoogleProvider({
      clientId: process.env.GOOGLE_CLIENT_ID || '',
      clientSecret: process.env.GOOGLE_CLIENT_SECRET || '',
    }),
  ],
  callbacks: {
    async jwt({ token, account, user }) {
      // Initial sign-in: exchange the Google ID token for our backend JWT.
      if (account && user) {
        try {
          const res = await fetch(`${SAAS_API_URL}/api/v1/auth/google`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id_token: account.id_token }),
          })
          if (res.ok) {
            const data = await res.json()
            token.accessToken = data.access_token
            token.tenantId = data.tenant_id
            token.backendTokenExpiry = Date.now() + BACKEND_TOKEN_TTL_MS
          } else {
            console.warn('[nextauth] backend exchange failed:', res.status)
          }
        } catch (err) {
          console.warn('[nextauth] backend exchange error:', err)
        }
      }

      // Subsequent session reads: the NextAuth session lives ~30 days but the
      // backend JWT only 24h — re-mint it before it lapses. (The BFF proxy
      // also refreshes per-request; this path persists whenever the session
      // endpoint is hit, e.g. sign-in follow-up fetches.)
      if (token.accessToken && !account) {
        const expiry = token.backendTokenExpiry ?? 0
        if (expiry - Date.now() < BACKEND_REFRESH_MARGIN_MS) {
          const fresh = await refreshBackendToken(token.accessToken)
          if (fresh) {
            token.accessToken = fresh.accessToken
            token.tenantId = fresh.tenantId
            token.backendTokenExpiry = Date.now() + BACKEND_TOKEN_TTL_MS
          }
        }
      }
      return token
    },
    async session({ session, token }: { session: Session; token: JWT }) {
      // Deliberately omit accessToken: the backend bearer must never reach
      // client JS. It stays in the encrypted session JWT (server-readable via
      // getToken) and is attached server-side by the /api/backend BFF proxy.
      return {
        ...session,
        user: { ...session.user, id: token.sub },
        tenantId: token.tenantId,
      } as Session
    },
  },
  pages: { signIn: '/sign-in' },
  session: { strategy: 'jwt' },
  secret: process.env.NEXTAUTH_SECRET,
}
