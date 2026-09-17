import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'
import nuxtUI from '@nuxt/ui/vite'

export default defineConfig({
  plugins: [nuxtUI(), vue(), tailwindcss()],
  build: { rollupOptions: { output: { manualChunks: { echarts: ['echarts/core', 'vue-echarts'], vue: ['vue', 'vue-router', 'pinia'] } } } },
  server: {
    host: '127.0.0.1',
    port: 15000,
    proxy: {
      '/api': {
        target: 'http://localhost:15001',
        changeOrigin: true,
        ws: true,
        timeout: 120000,
        proxyTimeout: 120000
      }
    }
  }
})