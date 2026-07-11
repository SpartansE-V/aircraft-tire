import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { harnessFE } from '@harness-fe/vite'

// https://vite.dev/config/
// ponytail: harnessFE is dev-only agent tooling — keep it out of the prod bundle.
// The dev server proxies /api to the FastAPI backend so the app calls same-origin relative paths
// (no CORS, no absolute URL baked into the bundle). Override the target with VITE_API_PROXY when the
// backend runs elsewhere; in prod the static host reverse-proxies /api the same way.
const API_PROXY = process.env.VITE_API_PROXY ?? 'http://localhost:8000'

export default defineConfig(({ command }) => ({
  plugins: [react(), tailwindcss(), ...(command === 'serve' ? [harnessFE()] : [])],
  server: {
    proxy: {
      '/api': { target: API_PROXY, changeOrigin: true },
    },
  },
}))
