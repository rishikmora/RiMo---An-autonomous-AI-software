/** @type {import('next').NextConfig} */
const API_BASE = process.env.RIMO_API_URL || "http://localhost:8000";
const nextConfig = {
  reactStrictMode: true,
  output: "standalone",
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${API_BASE}/api/:path*` },
      { source: "/backend-health", destination: `${API_BASE}/health` },
    ];
  },
};
export default nextConfig;
