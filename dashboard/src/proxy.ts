import { NextRequest, NextResponse } from 'next/server'
import { getToken } from 'next-auth/jwt'

// SaaS-mode auth guard (Next 16 "proxy" convention). In OSS self-host mode
// (flag off) this is a pass-through, so the public repo's behavior is unchanged.
// In SaaS mode the app pages require a session; unauthenticated visitors go to
// /sign-in.
const PROTECTED = ['/overview', '/detections', '/onboarding', '/settings']

export async function proxy(req: NextRequest) {
  if (process.env.NEXT_PUBLIC_SAAS !== '1') return NextResponse.next()

  const { pathname } = req.nextUrl
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
