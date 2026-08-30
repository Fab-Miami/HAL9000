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
        target: 'http://87.99.142.137',
        ws: true,
        changeOrigin: true
      }
    }
  }
});
