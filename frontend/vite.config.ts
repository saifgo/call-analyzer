import path from "node:path"
import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

// Built into the Python package so `python -m call_analyzer ui` serves it without Node.
// In dev (`npm run dev`), API and share/export requests go to the running Python server.
export default defineConfig({
  base: "/static/",
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
  build: { outDir: "../call_analyzer/web/static", emptyOutDir: true },
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8765",
      "/share": "http://127.0.0.1:8765",
    },
  },
})
