import { defineConfig } from 'vitest/config';

// Explicit, self-contained config so vitest does not climb the directory tree
// and inherit a sibling package's config (the pisama monorepo has a frontend
// vitest config with an unrelated setupFiles path). Kept as .mjs so it is not
// subject to the community-nodes `**/*.ts` eslint ruleset.
export default defineConfig({
	test: {
		root: '.',
		include: ['test/**/*.test.mjs'],
		environment: 'node',
		setupFiles: [],
	},
});
