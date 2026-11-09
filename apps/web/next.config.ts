import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  experimental: {
    externalDir: true,
  },
  async headers() {
    const headers = [
      { key: "Cache-Control", value: "private, no-store, max-age=0, must-revalidate" },
      { key: "CDN-Cache-Control", value: "no-store" },
      { key: "Vercel-CDN-Cache-Control", value: "no-store" },
      { key: "X-Robots-Tag", value: "noindex, nofollow, noarchive" },
      { key: "Referrer-Policy", value: "no-referrer" },
    ];
    return ["/collections/yoon-fest/:path*", "/api/yoon-fest/:path*", "/submissions/:path*", "/api/jobs/:path*", "/admin/:path*"].map((source) => ({ source, headers }));
  },
  async redirects() {
    return [
      {
        source: "/index",
        destination: "/",
        permanent: true,
      },
      {
        source: "/index.html",
        destination: "/",
        permanent: true,
      },
    ];
  },
};

export default nextConfig;
