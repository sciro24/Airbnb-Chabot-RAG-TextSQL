import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In dev il frontend gira su :5173 e inoltra /api al backend FastAPI su :8000.
// In build produce web/dist, servito da FastAPI (StaticFiles) in mono-processo.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { "/api": "http://localhost:8000" },
  },
});
