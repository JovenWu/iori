import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // The container is reached via localhost:3000 while pages may open on
  // 127.0.0.1 — without this the /_next/hmr socket is rejected cross-origin.
  allowedDevOrigins: ["127.0.0.1", "localhost"],
  // Slim production image — frontend/Dockerfile runs .next/standalone.
  output: "standalone",
  // Docker Desktop mounts don't reliably deliver filesystem events to the
  // container, so Turbopack can miss edits. Poll instead — enabled only
  // where the env is set (compose), keeping host dev event-driven.
  watchOptions: process.env.WATCHPACK_POLLING
    ? { pollIntervalMs: 1000 }
    : undefined,
};

export default nextConfig;
