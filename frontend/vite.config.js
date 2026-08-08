import { defineConfig } from 'vite';

export default defineConfig({
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    rollupOptions: {
      input: {
        main: './index.html',
      },
    },
  },
  publicDir: false,
  server: { open: false },
  test: {
    globals: true,
    environment: 'jsdom',
  },
});
