import type { NextConfig } from "next";
import { PHASE_DEVELOPMENT_SERVER } from "next/constants";

const sharedConfig: NextConfig = {
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["./scripts/tailwind-loader.cjs"],
        as: "*.css",
      },
    },
  },
};

export default function nextConfig(phase: string): NextConfig {
  if (phase !== PHASE_DEVELOPMENT_SERVER) {
    return { ...sharedConfig, output: "export" };
  }

  return {
    ...sharedConfig,
    experimental: {
      // Avoid restoring stale CSS transforms across development restarts.
      turbopackFileSystemCacheForDev: false,
      proxyTimeout: 30_000,
    },
    async rewrites() {
      return [{ source: "/api/:path*", destination: "http://127.0.0.1:8000/:path*" }];
    },
  };
}
