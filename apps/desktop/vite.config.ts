import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";

function runtimeToken(): string {
  const candidates = [
    process.env.JARVIS_DATA_DIR,
    process.platform === "win32" ? path.join(process.env.LOCALAPPDATA || "", "JARVIS") : "",
    path.join(os.homedir(), ".local", "share", "jarvis"),
    "/tmp/jarvis-preview",
  ].filter(Boolean) as string[];
  for (const dir of candidates) {
    try {
      const token = fs.readFileSync(path.join(dir, "runtime-token"), "utf8").trim();
      if (token) return token;
    } catch {
      /* try next */
    }
  }
  return process.env.JARVIS_RUNTIME_TOKEN || "";
}

const PROD_CSP = [
  // The packaged renderer runs from file://, where 'self' alone is unreliable.
  // `file:` keeps local assets working without allowing remote code or inline scripts.
  "default-src 'self' file:",
  "script-src 'self' file:",
  "style-src 'self' 'unsafe-inline' file:",
  "img-src 'self' data: blob: file:",
  "font-src 'self' data: file:",
  "connect-src 'self' http://127.0.0.1:8765 http://localhost:8765",
  "media-src 'self' blob:",
  "object-src 'none'",
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
].join("; ");

// Dev only: Vite/React Fast Refresh inject an inline module preamble and open an HMR
// websocket. Production keeps the strict policy above (no inline scripts, no ws:).
const DEV_CSP = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self' data:",
  "connect-src 'self' ws: wss: http://127.0.0.1:8765 http://localhost:8765",
  "media-src 'self' blob:",
  "object-src 'none'",
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
].join("; ");

const cspPlugin = {
  name: "jarvis-csp",
  transformIndexHtml(html: string, ctx: { server?: unknown }) {
    return html.replace("__JARVIS_CSP__", ctx.server ? DEV_CSP : PROD_CSP);
  },
};

export default defineConfig({
  root: "src/renderer",
  // Renderer is loaded from file:// in the packaged app; absolute /assets URLs would
  // resolve to the filesystem root and the window would stay blank.
  base: "./",
  plugins: [react(), cspPlugin],
  build: { outDir: "../../dist/renderer", emptyOutDir: true },
  server: {
    host: "0.0.0.0",
    port: 5173,
    strictPort: true,
    allowedHosts: true,
    proxy: {
      "/api": {
        target: process.env.JARVIS_BACKEND_URL || "http://127.0.0.1:8765",
        changeOrigin: true,
        headers: { Authorization: `Bearer ${runtimeToken()}` },
      },
      "/health": {
        target: process.env.JARVIS_BACKEND_URL || "http://127.0.0.1:8765",
        changeOrigin: true,
      },
    },
  },
});
