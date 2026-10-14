import path from 'node:path';
import { defineConfig } from 'vitest/config';
/**
 * Konfigurasi unit test frontend_app_v2 (F1).
 *
 * - `environment: 'node'` — **jsdom tidak jalan di bun** (.clinerules §ENVIRONMENT).
 *   Komponen diuji dengan `renderToString` + walker (`tests/helpers/react-tree.ts`),
 *   bukan DOM; jangan klaim DOM/event browser.
 * - Alias `@` disalin dari `vite.config.ts` supaya test memakai path yang sama.
 * - Konfigurasi ini terpisah dari `vite.config.ts` agar plugin build (react/tailwind)
 *   tidak ikut dijalankan saat test.
 */
export default defineConfig({
  resolve: {
    alias: {
      '@': path.resolve(import.meta.dirname, './src'),
    },
  },
  test: {
    environment: 'node',
    include: ['tests/**/*.test.{ts,tsx}'],
  },
});
