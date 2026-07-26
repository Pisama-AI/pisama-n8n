import { NextResponse } from 'next/server'

import productManifest from '@/data/product-capabilities.generated.json'
import { buildProvenance } from '@/lib/provenance'

/**
 * Public, same-origin copy of the canonical product contract.
 *
 * Both hosted dashboards expose the same path as the self-host FastAPI server, so
 * evaluators do not need to infer which backend origin is current. The response body
 * stays schema-compatible with the canonical manifest; deployment provenance rides
 * in headers instead of changing that contract.
 */
export function GET() {
  const provenance = buildProvenance()
  const headers = new Headers({
    'Cache-Control': 'public, max-age=0, must-revalidate',
    'X-Pisama-Build-Revision': provenance.build_revision,
    'X-Pisama-Source-Repository': provenance.source_repository,
  })
  if (provenance.source_revision_url) {
    headers.set('X-Pisama-Source-Revision-URL', provenance.source_revision_url)
  }

  return NextResponse.json(productManifest, { headers })
}
