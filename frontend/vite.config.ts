import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'
import nuxtUI from '@nuxt/ui/vite'

const apiUrl = process.env.VITE_API_URL || 'http://localhost:8088'
const rpcUrl = process.env.VITE_RPC_API_URL || 'http://localhost:8080'

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
        target: apiUrl,
        changeOrigin: true,
        ws: true,
        timeout: 120000,
        proxyTimeout: 120000
      },
      '/trades': {
        target: apiUrl,
        changeOrigin: true
      },
      '/api/rpc': {
        target: rpcUrl,
        changeOrigin: true,
        ws: true,
        rewrite: (path) => path.replace(/^\/api\/rpc/, ''),
        timeout: 120000,
        proxyTimeout: 120000
      }
    }
  }
})
