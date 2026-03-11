import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [vue(), tailwindcss()],
  server: {
    allowedHosts: ['quiz.nianyu.qzz.io'],
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:5003',
        changeOrigin: true,
      },
    },
  },
})
