import react from "@vitejs/plugin-react";
import { resolve } from "node:path";
import { defineConfig } from "vite";

// Runs examples/host-app against the BUILT package (npm run build:sdk first), exactly as an
// external app would consume it.
const pkg = resolve(import.meta.dirname, "../packages/agent-ui");

export default defineConfig({
  root: resolve(import.meta.dirname, "examples/host-app"),
  plugins: [react()],
  resolve: {
    // Peer dependencies come from the host app (as with any npm install).
    dedupe: [
      "react",
      "react-dom",
      "@xyflow/react",
      "@dagrejs/dagre",
      "lucide-react",
    ],
    alias: [
      {
        find: "@easy-access/agent-ui/styles.css",
        replacement: resolve(pkg, "dist/styles.css"),
      },
      {
        find: /^@easy-access\/agent-ui$/,
        replacement: resolve(pkg, "dist/index.js"),
      },
    ],
  },
  server: {
    port: 5175,
    fs: { allow: [resolve(import.meta.dirname, ".."), pkg] },
  },
  build: {
    outDir: resolve(import.meta.dirname, "node_modules/.tmp/host-app-dist"),
    emptyOutDir: true,
  },
});
