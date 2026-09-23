import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'
import nuxtUI from '@nuxt/ui/vite'

export default defineConfig({
  plugins: [
    nuxtUI({
      ui: {
        colors: {
          primary: 'purple',
          neutral: 'slate'
        }
      }
    }),
    vue(),
    tailwindcss()
  ],
  build: { rollupOptions: { output: { manualChunks: { echarts: ['echarts/core', 'vue-echarts'], vue: ['vue', 'vue-router', 'pinia'] } } } },
  server: {
    host: '127.0.0.1',
    port: 15000,
    proxy: {
      '/api': {
        target: 'http://localhost:8088',
        changeOrigin: true,
        ws: true,
        timeout: 120000,
        proxyTimeout: 120000
      },
      // Trade JSON blobs are served by the backend's /trades static mount.
      // Without this, dev-mode requests fall through to the SPA fallback and
      // return index.html with status 200, which the trade views silently
      // parse as "no trades".
      '/trades': {
        target: 'http://localhost:8088',
        changeOrigin: true
      },
      // RPC API Server (live trading + analysis endpoints)
      '/api/rpc': {
        target: 'http://localhost:8080',
        changeOrigin: true,
        ws: true,
        rewrite: (path) => path.replace(/^\/api\/rpc/, ''),
        timeout: 120000,
        proxyTimeout: 120000
      }
    }
  }
})