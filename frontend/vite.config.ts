import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

// Dev server proxies /api to the FastAPI backend, so the browser talks to one origin.
// 127.0.0.1 (not "localhost"): Node resolves localhost to IPv6 ::1, uvicorn listens on IPv4.
// (no CORS setup needed during development).
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  return {
    plugins: [react(), tailwindcss()],
    server: {
      port: 5173,
      proxy: {
        "/api": { target: env.VITE_PROXY_TARGET || "http://127.0.0.1:8000", changeOrigin: true },
      },
    },
  };
});
