/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Pin Turbopack's workspace root to this directory so Next doesn't walk up to
  // an unrelated parent package-lock.json when resolving build output.
  turbopack: {
    root: __dirname,
  },
};

module.exports = nextConfig;
