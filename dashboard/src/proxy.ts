import { NextRequest, NextResponse } from 'next/server'
import { getToken } from 'next-auth/jwt'

// Next 16 "proxy" convention. Two deploy modes gate the dashboard routes;
// fair-code self-host (neither flag set) is a pass-through, so public-repo behavior
// is unchanged.
//   NEXT_PUBLIC_READONLY=1 — the marketing-only deploy (n8n.pisama.ai). The
//     retired public demo: dashboard routes redirect to the landing.
//   NEXT_PUBLIC_SAAS=1 — the hosted app (app.n8n.pisama.ai): dashboard routes
//     require a session; unauthenticated visitors go to /sign-in.
const PROTECTED = ['/overview', '/detections', '/onboarding', '/settings']

export async function proxy(req: NextRequest) {
  const { pathname } = req.nextUrl

  // Marketing-only deploy: no live demo — bounce the dashboard routes to the
  // landing. (Runs only for the matched routes, so `/` never loops.)
  if (process.env.NEXT_PUBLIC_READONLY === '1') {
    return NextResponse.redirect(new URL('/', req.url))
  }

  if (process.env.NEXT_PUBLIC_SAAS !== '1') return NextResponse.next()

  if (!PROTECTED.some((p) => pathname === p || pathname.startsWith(`${p}/`))) {
    return NextResponse.next()
  }
  const token = await getToken({ req, secret: process.env.NEXTAUTH_SECRET })
  if (!token) {
    const signIn = new URL('/sign-in', req.url)
    signIn.searchParams.set('callbackUrl', pathname)
    return NextResponse.redirect(signIn)
  }
  return NextResponse.next()
}

export const config = {
  matcher: ['/overview/:path*', '/detections/:path*', '/onboarding/:path*', '/settings/:path*'],
}
