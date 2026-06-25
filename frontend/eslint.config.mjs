// Next.js 16 removed the `next lint` CLI in favor of running ESLint directly.
// eslint-config-next now ships a native ESLint 9 flat-config array (it already
// bundles next/core-web-vitals + next/typescript), so it's spread in as-is —
// no FlatCompat bridging needed (and FlatCompat hits a circular-structure
// validation bug against this package's plugin objects in this version combo).
import nextConfig from "eslint-config-next/core-web-vitals";

const config = [
  {
    ignores: [
      "node_modules/**",
      ".next/**",
      "out/**",
      "build/**",
      "next-env.d.ts",
    ],
  },
  ...nextConfig,
];

export default config;
