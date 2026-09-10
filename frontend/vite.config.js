import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

/**
 * Il front end parla solo con il backend Node: le chiamate /api e le immagini
 * /charts sono inoltrate via proxy, così in sviluppo non servono URL assoluti
 * né configurazioni CORS lato browser.
 */
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://localhost:3001", changeOrigin: true },
      "/charts": { target: "http://localhost:3001", changeOrigin: true },
    },
  },
});
