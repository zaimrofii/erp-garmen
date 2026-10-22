import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import path from 'node:path';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5173,
    strictPort: true,
    // K5.5 — SENGAJA tanpa proxy `/media`. Resolusi URL media dilakukan di aplikasi
    // (`src/lib/media-url.ts`: URL relatif di-prefix origin `VITE_API_BASE_URL`).
    // Percobaan proxy Vite → Django `runserver` di lingkungan bun ini membalas 502
    // (body berkas ikut ter-stream tapi status salah), sedangkan `:8000` langsung 200.
  },
  build: {
    // Fix #18C — Recharts dipisah ke chunk vendor agar chunk chat < 500 kB.
    rolldownOptions: {
      output: {
        manualChunks: (id: string) => {
          if (
            id.includes('node_modules/recharts') ||
            id.includes('node_modules/victory-vendor') ||
            id.includes('node_modules/d3-')
          ) {
            return 'recharts';
          }
          return undefined;
        },
      },
    },
  },
});
