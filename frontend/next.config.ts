import type { NextConfig } from "next";

// The backend issues an httponly session cookie scoped to whichever origin
// the browser thinks it's talking to. Proxying /api and /auth through the
// Next.js server (rather than fetching the backend's origin directly from
// client JS) keeps the browser on one origin, so that cookie round-trips
// normally instead of being dropped as cross-site.
const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${BACKEND_URL}/api/:path*` },
      { source: "/auth/:path*", destination: `${BACKEND_URL}/auth/:path*` },
    ];
  },
};

export default nextConfig;
