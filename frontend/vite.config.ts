import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  base: '/static/spa/',
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      '/admin': 'http://127.0.0.1:8000',
      '/api': 'http://127.0.0.1:8000',
      '/static': 'http://127.0.0.1:8000',
      '/r': 'http://127.0.0.1:8000',
      '/health': 'http://127.0.0.1:8000',
      '/indicators': 'http://127.0.0.1:8000',
    },
  },
})
