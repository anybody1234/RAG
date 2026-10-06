import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Chuyển mọi request /api sang backend FastAPI khi chạy dev.
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
})
