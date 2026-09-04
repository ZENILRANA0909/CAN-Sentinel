import path from 'node:path'
import react from '@vitejs/plugin-react'
// vitest/config re-exports Vite's defineConfig with the `test` block typed.
import { defineConfig } from 'vitest/config'

// The backend origin the dev server proxies to. Overridable so the dashboard
// can be pointed at a backend running elsewhere - a different port or host.
const BACKEND_ORIGIN = process.env.VITE_PROXY_TARGET ?? 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': path.resolve(__dirname, './src') },
  },
  server: {
    port: 5173,
    host: true,
    // Proxying keeps the browser on one origin in development, so CORS and
    // WebSocket upgrades behave exactly as they do behind a production proxy.
    proxy: {
      '/api': { target: BACKEND_ORIGIN, changeOrigin: true },
      '/ws': { target: BACKEND_ORIGIN, ws: true, changeOrigin: true },
    },
  },
  preview: { port: 4173, host: true },
  build: {
    outDir: 'dist',
    sourcemap: false,
    chunkSizeWarningLimit: 900,
    rollupOptions: {
      output: {
        // Charts are the heaviest dependency and are not needed on first paint;
        // splitting them keeps the initial bundle small.
        manualChunks: {
          react: ['react', 'react-dom', 'react-router-dom'],
          charts: ['recharts'],
        },
      },
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
  },
})
