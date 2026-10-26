import path from "node:path"
import react from "@vitejs/plugin-react"
import tailwindcss from "@tailwindcss/vite"
import { defineConfig } from "vite"

export default defineConfig(({ command }) => ({
  base: command === "build" ? "/assets/hospitality_suite/frontend/" : "/",
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
  build: {
    outDir: "../hospitality_suite/public/frontend",
    emptyOutDir: true,
    rollupOptions: { input: {
      index: path.resolve(__dirname, "index.html"),
      portal: path.resolve(__dirname, "portal.html"),
      confirmation: path.resolve(__dirname, "confirmation.html"),
      guest: path.resolve(__dirname, "guest.html"),
    } },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.HOSPITALITY_API_TARGET || "http://localhost:8000",
        headers: { Host: process.env.HOSPITALITY_SITE_HOST || "hospitality.localhost" },
      },
    },
  },
}))
