import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: Number(process.env.FRONTEND_PORT) || 12001,
    proxy: {
      '/api': 'http://127.0.0.1:' + (process.env.BACKEND_PORT || '12002'),
      '/v1': 'http://127.0.0.1:' + (process.env.BACKEND_PORT || '12002'),
    },
  },
})
