import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

// The browser only ever talks to this Vite server; API paths are proxied to the backend.
// So a phone needs just one address (http://<LAN-IP>:5173) and there is no CORS to configure.
// xfwd adds X-Forwarded-For with the real client address: the backend uses it so that /demo/*
// (courier codes) is not opened to the whole network just because the proxy itself is local.
const API_PATHS = ["/orders", "/boxes", "/health", "/demo"];

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const target = env.API_PROXY_TARGET || "http://127.0.0.1:8000";
  const proxy = Object.fromEntries(API_PATHS.map((p) => [p, { target, changeOrigin: true, xfwd: true }]));
  return {
    plugins: [react()],
    server: { host: true, port: 5173, strictPort: true, proxy },
    preview: { host: true, port: 5173, strictPort: true, proxy },
  };
});
