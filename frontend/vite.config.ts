import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    host: "0.0.0.0",
    port: 11003,
    headers: {
      "Cross-Origin-Opener-Policy": "same-origin",
    },
    proxy: {
      "/api/icons": {
        target: "http://127.0.0.1:8800",
        changeOrigin: true,
      },
      "/api": {
        target: "http://127.0.0.1:11001",
        changeOrigin: true,
        timeout: 300000,
        proxyTimeout: 300000,
      },
      "/ws": {
        target: "ws://127.0.0.1:11001",
        ws: true,
      },
      "/temp": {
        target: "http://127.0.0.1:11001",
        changeOrigin: true,
        timeout: 300000,
        proxyTimeout: 300000,
      },
      "/cutia": {
        target: "http://127.0.0.1:4100",
        changeOrigin: true,
      },
      "/social": {
        target: "http://127.0.0.1:5173",
        changeOrigin: true,
        ws: true,
      },
    },
  },
});
