/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // In development the browser talks to Next on :3000 and the API on
  // :8000. In the container stack Caddy serves both from one origin, so
  // this rewrite is a no-op there and the client code never needs to know
  // which environment it is in -- it always calls same-origin /api/*.
  // The staff pages now live under /settings; old bookmarks keep working.
  async redirects() {
    return [
      { source: "/faculty/activity", destination: "/settings/activity", permanent: true },
      { source: "/faculty/marks", destination: "/settings/marks", permanent: true },
      { source: "/faculty/sessions", destination: "/settings/sessions", permanent: true },
    ];
  },
  async rewrites() {
    const backend = process.env.BACKEND_INTERNAL_URL;
    if (!backend) return [];
    return [{ source: "/api/:path*", destination: `${backend}/api/:path*` }];
  },
};

export default nextConfig;
