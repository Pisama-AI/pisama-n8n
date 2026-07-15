import { encode } from 'next-auth/jwt'

// Must match the NEXTAUTH_SECRET the Playwright webServer boots `next dev` with
// (see playwright.config.ts). The test forges a session with this key; the app's
// proxy guard + BFF decode it with the same one.
export const NEXTAUTH_KEY = 'pisama-n8n-e2e-key-at-least-32-characters-xx'

// A forged NextAuth (v4) session cookie, so SaaS-guarded routes (proxy.ts) and the
// BFF accept the request without a real Google sign-in.
export async function sessionCookie(email = 'founder@pisama.ai') {
  const value = await encode({
    token: { name: email, email, accessToken: 'test-backend-jwt' },
    secret: NEXTAUTH_KEY,
  })
  return {
    name: 'next-auth.session-token',
    value,
    domain: 'localhost',
    path: '/',
    httpOnly: true,
    sameSite: 'Lax' as const,
  }
}
