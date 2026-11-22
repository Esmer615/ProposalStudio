import { defineConfig } from 'astro/config';

// Multi-page static build. FastAPI serves web/dist at 127.0.0.1:8010.
// Pages are emitted as .html files (product.html, map.html, ...).
export default defineConfig({
  output: 'static',
  build: { format: 'file' },
  vite: {
    server: {
      proxy: {
        '/api': { target: 'http://127.0.0.1:8010', changeOrigin: true },
      },
    },
  },
});
