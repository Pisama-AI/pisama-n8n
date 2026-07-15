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
            token.backendTokenExpiry = Date.now() + 23 * 60 * 60 * 1000
          } else {
            console.warn('[nextauth] backend exchange failed:', res.status)
          }
        } catch (err) {
          console.warn('[nextauth] backend exchange error:', err)
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
