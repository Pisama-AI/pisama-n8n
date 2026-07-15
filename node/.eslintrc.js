/**
 * ESLint config for the Pisama n8n community node.
 *
 * Uses eslint-plugin-n8n-nodes-base to enforce the structural conventions the
 * n8n verified-community-node review checks (node/credential descriptions,
 * parameter shapes, naming). Scoped to the TypeScript sources; the package.json
 * ruleset (`plugin:n8n-nodes-base/community`) additionally requires
 * jsonc-eslint-parser and is run by the n8n reviewer via
 * `npx @n8n/scan-community-package`.
 */
module.exports = {
	root: true,
	env: { node: true, es6: true },
	parser: '@typescript-eslint/parser',
	parserOptions: { sourceType: 'module', ecmaVersion: 2020 },
	ignorePatterns: ['.eslintrc.js', 'gulpfile.js', 'index.js', 'dist/**', 'node_modules/**'],
	overrides: [
		{
			files: ['./credentials/**/*.ts'],
			plugins: ['eslint-plugin-n8n-nodes-base'],
			extends: ['plugin:n8n-nodes-base/credentials'],
			rules: {
				// We deliberately use a full HTTPS documentation URL, not a doc
				// slug; these rules would camelCase-mangle it.
				'n8n-nodes-base/cred-class-field-documentation-url-miscased': 'off',
				'n8n-nodes-base/cred-class-field-documentation-url-not-http-url': 'off',
			},
		},
		{
			files: ['./nodes/**/*.ts'],
			plugins: ['eslint-plugin-n8n-nodes-base'],
			extends: ['plugin:n8n-nodes-base/nodes'],
			rules: {
				// "Pisama" is a brand name (title case per our house style); the
				// action-casing rule would lowercase it.
				'n8n-nodes-base/node-param-operation-option-action-miscased': 'off',
			},
		},
	],
};
