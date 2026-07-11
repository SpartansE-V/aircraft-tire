import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { harnessFE } from '@harness-fe/vite'

// https://vite.dev/config/
// ponytail: harnessFE is dev-only agent tooling — keep it out of the prod bundle.
export default defineConfig(({ command }) => ({
  plugins: [react(), tailwindcss(), ...(command === 'serve' ? [harnessFE()] : [])],
  // Same-origin `/api` in dev so the browser never hits CORS: forward it to the FastAPI
  // backend (`make run`, default :8000). Point elsewhere with VITE_API_PROXY.
  server: {
    proxy: {
      '/api': {
        target: process.env.VITE_API_PROXY ?? 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
}))
