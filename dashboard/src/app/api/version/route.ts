import { NextResponse } from 'next/server'

/**
 * Build-provenance endpoint — the dashboard's answer to the Fly backends' /healthz
 * `build_revision`. The deploy script (`deploy/deploy-dashboard.sh`) bakes the git SHA
 * into NEXT_PUBLIC_BUILD_REVISION at build time (`-b` build-env) so this route reports
 * exactly which commit is serving. VERCEL_GIT_COMMIT_SHA is the fallback for a
 * dashboard-linked Git deploy (there is none today — both Vercel projects are CLI-only),
 * and "unknown" mirrors the Dockerfile's default when nothing was injected.
 *
 * Same JSON key as the backends' /healthz, so the drift checker parses all five apps
 * with one regex. Env is fixed at build, but a plain (dynamic) handler is fine here — no
 * need to force-static; the value never changes for the life of a deployment either way.
 */
export function GET() {
  return NextResponse.json({
    build_revision:
      process.env.NEXT_PUBLIC_BUILD_REVISION ??
      (process.env.VERCEL_GIT_COMMIT_SHA ?? 'unknown'),
  })
}
