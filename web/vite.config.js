import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In dev il frontend gira su :5173 e inoltra /api al backend FastAPI su :8000.
// In build produce web/dist, servito da FastAPI (StaticFiles) in mono-processo.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { "/api": "http://localhost:8000" },
  },
  build: {
    // Separa i vendor pesanti in chunk distinti (evita il warning >500KB).
    rollupOptions: {
      output: {
        manualChunks: {
          react: ["react", "react-dom", "react-router-dom"],
          leaflet: ["leaflet", "react-leaflet"],
          charts: ["recharts"],
          markdown: ["react-markdown", "remark-gfm"],
        },
      },
    },
  },
});
