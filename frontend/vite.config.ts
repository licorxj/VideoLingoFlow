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
  // 依赖预构建：显式声明重依赖，避免 dev 首次访问时逐个模块请求（lucide 图标库尤其明显）
  optimizeDeps: {
    include: [
      "lucide-react",
      "@xyflow/react",
      "recharts",
      "wavesurfer.js",
      "marked",
      "html-to-image",
      "react-router-dom",
      "@tanstack/react-query",
      "zustand",
    ],
  },
  build: {
    target: "es2020",
    // 生产不产出 sourcemap：devtools 不再驻留 map，可显著降低浏览器内存占用
    sourcemap: false,
    // 构建期不再做 gzip 体积统计（大包时省时省内存）
    reportCompressedSize: false,
    chunkSizeWarningLimit: 1200,
    // 10KB 以下资源内联，减少首屏请求数
    assetsInlineLimit: 10240,
    rollupOptions: {
      output: {
        // 按依赖族拆包：首屏只加载 react + 布局所需 vendor，
        // 画布/图表/波形/ Markdown 等重依赖按需再加载（配合路由懒加载效果最佳）
        advancedChunks: {
          groups: [
            { name: "vendor-react", test: /node_modules[\\/](react|react-dom|scheduler)[\\/]/, priority: 30 },
            { name: "vendor-flow", test: /node_modules[\\/]@xyflow[\\/]/, priority: 25 },
            { name: "vendor-charts", test: /node_modules[\\/](recharts|d3-)[\\/]/, priority: 20 },
            { name: "vendor-icons", test: /node_modules[\\/]lucide-react[\\/]/, priority: 20 },
            { name: "vendor-audio", test: /node_modules[\\/]wavesurfer/, priority: 20 },
            { name: "vendor-text", test: /node_modules[\\/](marked|srt-parser-2|html-to-image)[\\/]/, priority: 15 },
            { name: "vendor-radix", test: /node_modules[\\/]@radix-ui[\\/]/, priority: 15 },
          ],
        },
      },
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
