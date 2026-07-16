import { NextRequest, NextResponse } from 'next/server'
import { encode, getToken, type JWT } from 'next-auth/jwt'

import {
  BACKEND_REFRESH_MARGIN_MS,
  BACKEND_TOKEN_TTL_MS,
  refreshBackendToken,
  SAAS_API_URL,
  type RefreshedBackendToken,
} from '@/lib/saasAuth'

/**
 * BFF proxy (SaaS mode) — the single egress from the browser to the SaaS API.
 * Ported from the pisama monorepo's /api/backend proxy, minus impersonation and
 * dev-bypass. The browser calls same-origin /api/backend/<path> with the
 * httpOnly session cookie; this handler resolves the backend bearer SERVER-SIDE
 * and attaches it — the raw JWT never reaches client JS.
 *
 * Token lifetime: the NextAuth session lives ~30 days but the backend JWT only
 * 24h. This proxy re-mints the bearer via /api/v1/auth/refresh when it is near
 * (or past) expiry, retries once on an upstream 401, and writes the fresh
 * bearer back into the encrypted session cookie. The cookie write matters:
 * this app has no SessionProvider, so the NextAuth jwt callback — the usual
 * persistence point — effectively never runs after sign-in.
 */

// NextAuth v4 session cookie names (secure prefix on https deployments).
const SESSION_COOKIE = 'next-auth.session-token'
const SECURE_SESSION_COOKIE = '__Secure-next-auth.session-token'
// NextAuth v4 default session maxAge; keeps the re-encoded cookie in step.
const SESSION_MAX_AGE_S = 30 * 24 * 60 * 60

async function forward(req: NextRequest, path: string[], bearer: string): Promise<Response> {
  const url = `${SAAS_API_URL}/${path.join('/')}${req.nextUrl.search}`
  const headers: Record<string, string> = { Authorization: `Bearer ${bearer}` }
  const contentType = req.headers.get('content-type')
  if (contentType) headers['Content-Type'] = contentType
  const accept = req.headers.get('accept')
  if (accept) headers['Accept'] = accept

  const hasBody = req.method !== 'GET' && req.method !== 'HEAD'
  const body = hasBody ? await req.arrayBuffer() : undefined

  // Bound the upstream call so the BFF 504s instead of holding the browser
  // connection open when the backend hangs.
  const controller = new AbortController()
  const timeoutId = setTimeout(() => controller.abort(), 60_000)
  try {
    return await fetch(url, {
      method: req.method,
      headers,
      body,
      cache: 'no-store',
      signal: controller.signal,
    })
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') {
      return new Response(JSON.stringify({ detail: 'Upstream request timed out' }), {
        status: 504,
        headers: { 'Content-Type': 'application/json' },
      })
    }
    throw e
  } finally {
    clearTimeout(timeoutId)
  }
}

/** Re-encode the session JWT with the re-minted bearer and set it on the
 * response, so the refresh survives this request. Best-effort: on any failure
 * the fresh bearer already served this request and the next one re-refreshes. */
async function persistRefresh(
  req: NextRequest,
  out: NextResponse,
  token: JWT,
  fresh: RefreshedBackendToken,
): Promise<void> {
  const secret = process.env.NEXTAUTH_SECRET
  if (!secret) return
  const cookieName = req.cookies.has(SECURE_SESSION_COOKIE) ? SECURE_SESSION_COOKIE : SESSION_COOKIE
  if (!req.cookies.has(cookieName)) return // chunked/absent cookie — skip
  try {
    const encoded = await encode({
      token: {
        ...token,
        accessToken: fresh.accessToken,
        tenantId: fresh.tenantId,
        backendTokenExpiry: Date.now() + BACKEND_TOKEN_TTL_MS,
      },
      secret,
      maxAge: SESSION_MAX_AGE_S,
    })
    out.cookies.set(cookieName, encoded, {
      httpOnly: true,
      sameSite: 'lax',
      path: '/',
      secure: cookieName === SECURE_SESSION_COOKIE,
      maxAge: SESSION_MAX_AGE_S,
    })
  } catch {
    // Leave the old cookie in place.
  }
}

async function handle(
  req: NextRequest,
  ctx: { params: Promise<{ path: string[] }> },
): Promise<NextResponse> {
  const { path } = await ctx.params
  const token = await getToken({ req, secret: process.env.NEXTAUTH_SECRET })
  if (!token?.accessToken) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
  }

  let bearer = token.accessToken
  let refreshed: RefreshedBackendToken | null = null

  // Proactive: re-mint when the stored bearer is near or past its 24h expiry.
  const expiry = token.backendTokenExpiry ?? 0
  if (expiry - Date.now() < BACKEND_REFRESH_MARGIN_MS) {
    refreshed = await refreshBackendToken(bearer)
    if (refreshed) bearer = refreshed.accessToken
  }

  // Clone before forwarding so a 401 retry can re-read the request body.
  const retryable = req.clone() as NextRequest
  let res = await forward(req, path, bearer)

  // Reactive: one refresh+retry on upstream 401 (expiry estimate can drift from
  // the token's real exp). Pointless if this request already minted the bearer.
  if (res.status === 401 && !refreshed) {
    refreshed = await refreshBackendToken(bearer)
    if (refreshed) {
      void res.body?.cancel()
      res = await forward(retryable, path, refreshed.accessToken)
    }
  }

  // Stream the body straight through (SSE and large payloads pass unbuffered).
  const out = new NextResponse(res.body, { status: res.status })
  const ct = res.headers.get('content-type')
  if (ct) out.headers.set('content-type', ct)
  const cc = res.headers.get('cache-control')
  if (cc) out.headers.set('cache-control', cc)

  if (refreshed) await persistRefresh(req, out, token, refreshed)
  return out
}

export const GET = handle
export const POST = handle
export const PUT = handle
export const PATCH = handle
export const DELETE = handle
