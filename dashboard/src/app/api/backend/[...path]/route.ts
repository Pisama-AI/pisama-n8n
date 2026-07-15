import { NextRequest, NextResponse } from 'next/server'
import { getToken } from 'next-auth/jwt'

import { SAAS_API_URL } from '@/lib/saasAuth'

/**
 * BFF proxy (SaaS mode) — the single egress from the browser to the SaaS API.
 * Ported from the pisama monorepo's /api/backend proxy, minus impersonation and
 * dev-bypass. The browser calls same-origin /api/backend/<path> with the
 * httpOnly session cookie; this handler resolves the backend bearer SERVER-SIDE
 * and attaches it — the raw JWT never reaches client JS.
 */

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

async function handle(
  req: NextRequest,
  ctx: { params: Promise<{ path: string[] }> },
): Promise<NextResponse> {
  const { path } = await ctx.params
  const token = await getToken({ req, secret: process.env.NEXTAUTH_SECRET })
  if (!token?.accessToken) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
  }

  const res = await forward(req, path, token.accessToken as string)

  // Stream the body straight through (SSE and large payloads pass unbuffered).
  const out = new NextResponse(res.body, { status: res.status })
  const ct = res.headers.get('content-type')
  if (ct) out.headers.set('content-type', ct)
  const cc = res.headers.get('cache-control')
  if (cc) out.headers.set('cache-control', cc)
  return out
}

export const GET = handle
export const POST = handle
export const PUT = handle
export const PATCH = handle
export const DELETE = handle
