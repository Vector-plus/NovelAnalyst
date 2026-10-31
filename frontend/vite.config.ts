import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// 后端 FastAPI 默认运行在 8000 端口，开发时通过代理转发 API 请求，避免跨域问题。
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/health': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
});
