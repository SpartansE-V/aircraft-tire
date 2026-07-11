import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { harnessFE } from '@harness-fe/vite'

// https://vite.dev/config/
// ponytail: harnessFE is dev-only agent tooling — keep it out of the prod bundle.
export default defineConfig(({ command }) => ({
  plugins: [react(), tailwindcss(), ...(command === 'serve' ? [harnessFE()] : [])],
}))
