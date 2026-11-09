import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  // The lazily loaded site twin chunk is ~780 kB, almost all deck.gl (~215 kB gzipped).
  build: { chunkSizeWarningLimit: 1000 },
  server: {
    port: 5173,
    // Same-origin API calls in dev: /api/* -> FastAPI on :8000
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
})
