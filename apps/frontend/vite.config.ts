import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Inside compose the API is reachable by service name; override for other setups.
const API = (globalThis as { process?: { env: Record<string, string | undefined> } }).process
  ?.env.API_ORIGIN ?? 'http://api:8000'

// Uploads are hundreds of megabytes and can take minutes, so the proxy must not
// impose its own timeout — the default would abort a large archive mid-flight.
const proxy = {
  target: API,
  changeOrigin: true,
  timeout: 0,
  proxyTimeout: 0,
}

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    proxy: {
      '/api': proxy,
      '/media': proxy,
      '/thumb': proxy,
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
})
