import packageMetadata from '../../package.json'

const SOURCE_REPOSITORY = 'https://github.com/Pisama-AI/pisama-n8n'
const FULL_GIT_SHA = /^[0-9a-f]{40}$/i

export function buildProvenance() {
  const buildRevision =
    [process.env.NEXT_PUBLIC_BUILD_REVISION, process.env.VERCEL_GIT_COMMIT_SHA]
      .map((candidate) => candidate?.trim())
      .find(Boolean) ?? 'unknown'
  const expectedSourceUrl = `${SOURCE_REPOSITORY}/commit/${buildRevision}`
  const configuredSourceUrl = process.env.NEXT_PUBLIC_SOURCE_REVISION_URL?.trim()

  return {
    service: packageMetadata.name,
    version: packageMetadata.version,
    build_revision: buildRevision,
    source_repository: SOURCE_REPOSITORY,
    source_revision_url:
      FULL_GIT_SHA.test(buildRevision) && configuredSourceUrl === expectedSourceUrl
        ? configuredSourceUrl
        : null,
  }
}
