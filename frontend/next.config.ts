import path from "node:path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /** Use this app folder as the tracing root when multiple lockfiles exist (e.g. parent + frontend). */
  outputFileTracingRoot: path.join(__dirname),
  async headers() {
    return [
      {
        source: '/(.*)',
        headers: [
          { key: 'Cross-Origin-Opener-Policy', value: 'same-origin' },
          { key: 'Cross-Origin-Embedder-Policy', value: 'require-corp' },
        ],
      },
    ];
  },
};

export default nextConfig;
