import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { resolve } from "node:path";
import { defineConfig } from "vite";

// Library build of the prop-driven components into packages/agent-ui (npm run build:sdk).
// React and the heavier UI libraries are peer dependencies supplied by the host app.
const external = [
  /^react($|\/)/,
  /^react-dom($|\/)/,
  /^@xyflow\/react/,
  /^@dagrejs\/dagre/,
  /^lucide-react/,
  /^@radix-ui\//,
];

export default defineConfig({
  plugins: [react(), tailwindcss()],
  publicDir: false,
  build: {
    outDir: resolve(import.meta.dirname, "../packages/agent-ui/dist"),
    emptyOutDir: true,
    sourcemap: true,
    cssCodeSplit: true,
    lib: {
      entry: {
        index: resolve(import.meta.dirname, "src/sdk/index.ts"),
        styles: resolve(import.meta.dirname, "src/sdk/styles.css"),
      },
      formats: ["es"],
    },
    rollupOptions: { external, output: { assetFileNames: "[name][extname]" } },
  },
});
