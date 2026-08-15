import { defineConfig } from 'vite';
import basicSsl from '@vitejs/plugin-basic-ssl';

export default defineConfig({
  plugins: [
    basicSsl()
  ],
  server: {
    host: '0.0.0.0',
    port: 8000,
    https: true,
    strictPort: true,
    proxy: {
      '/ws': {
        target: 'http://127.0.0.1:8001',
        ws: true,
        changeOrigin: true
      }
    }
  }
});
