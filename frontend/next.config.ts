import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Emit a self-contained Node server under .next/standalone so the Docker
  // image can run with just node (no npm install at runtime).
  output: "standalone",

  // Next 13+ dev server returns 403 on assets and refuses the HMR WebSocket
  // when requests come from a host it doesn't recognize (e.g. a LAN IP rather
  // than localhost). List every host you intend to reach the dev server from.
  // RFC 1918 wildcards are accepted — keep them broad for internal demos.
  allowedDevOrigins: [
    "localhost",
    "127.0.0.1",
    "192.168.1.*",
    "192.168.0.*",
    "10.0.0.*",
  ],
};

export default nextConfig;
