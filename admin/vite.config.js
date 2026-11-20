// Build statica servita da FastAPI: nessun servizio Node.js in esercizio.
//   npm ci && npm run build    -> ../app/venue_booking/static/admin/
//   npm run dev                -> http://localhost:5173/amministrazione (API e Bootstrap Italia dall'app su :8000)
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const backendUrl = process.env.SPAZIO_COMUNE_URL || "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  base: "/static/admin/",
  build: {
    outDir: "../app/venue_booking/static/admin",
    emptyOutDir: true,
    sourcemap: false,
  },
  server: {
    proxy: { "/api": backendUrl, "/static/bootstrap-italia": backendUrl, "/static/app.css": backendUrl },
  },
});
