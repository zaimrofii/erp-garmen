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
});
