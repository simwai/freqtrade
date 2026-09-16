import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [vue(), tailwindcss()],
  build: { rollupOptions: { output: { manualChunks: { echarts: ['echarts/core', 'vue-echarts'], vue: ['vue', 'vue-router', 'pinia'] } } } },
  server: {
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