import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { MENU_APPS, findActiveMenuPath, isPlaceholderApp, menuAppsForIds, resolveMenuTarget } from '@/app/menu-config';

/**
 * F5/5.1 — validasi `menu-config.ts`.
 *
 * "Tidak ada route yatim" dibuktikan dengan memindai `src/App.tsx`: setiap item yang
 * TIDAK disabled harus punya `path` yang cocok dengan salah satu `path="…"` di router.
 * (Tes berbasis sumber ini dipakai karena render halaman butuh Router+QueryClient.)
 */

const ROOT = path.resolve(import.meta.dirname, '../../..');

function routePaths(): string[] {
  const source = readFileSync(path.join(ROOT, 'src/App.tsx'), 'utf8');

  return [...source.matchAll(/path="([^"]+)"/g)].map((match) => match[1] ?? '');
}

describe('F5 — MENU_APPS', () => {
  it('11 app: 10 dari NAV_APPS (termasuk Finance F15 & Sales H2.1) + 1 placeholder (Master)', () => {
    expect(MENU_APPS.map((app) => app.id)).toEqual([
      'dashboard',
      'production',
      'inventory',
      'sales',
      'purchase',
      'quality',
      'reports',
      'settings',
      'ai',
      'finance',
      'master',
    ]);
  });

  it('id app unik & setiap app punya minimal satu item', () => {
    const ids = MENU_APPS.map((app) => app.id);

    expect(new Set(ids).size).toBe(ids.length);

    for (const app of MENU_APPS) {
      expect(app.items.length, app.id).toBeGreaterThan(0);
    }
  });

  it('TIDAK ADA route yatim: semua item enabled cocok dengan route di App.tsx', () => {
    const routes = routePaths();

    for (const app of MENU_APPS) {
      for (const item of app.items) {
        if (item.disabled === true) continue;

        expect(item.path, `${app.id}:${item.id}`).toBeDefined();
        expect(routes, `${app.id}:${item.path}`).toContain(item.path);
      }
    }
  });

  it('item placeholder: disabled + hint + TANPA path', () => {
    for (const app of MENU_APPS) {
      for (const item of app.items) {
        if (item.disabled !== true) continue;

        expect(item.hint, `${app.id}:${item.id}`).toBeTruthy();
        expect(item.path, `${app.id}:${item.id}`).toBeUndefined();
      }
    }
  });

  it('Master hanya berisi placeholder (Finance F15 & Sales H2.1 sudah REAL)', () => {
    for (const id of ['master']) {
      const app = MENU_APPS.find((candidate) => candidate.id === id);

      expect(app, id).toBeDefined();
      expect(isPlaceholderApp(app!), id).toBe(true);
    }
  });

  it('app nyata tidak dianggap placeholder (termasuk finance & sales)', () => {
    for (const id of [
      'dashboard',
      'production',
      'inventory',
      'purchase',
      'quality',
      'reports',
      'settings',
      'ai',
      'finance',
      'sales',
    ]) {
      const app = MENU_APPS.find((candidate) => candidate.id === id);

      expect(isPlaceholderApp(app!), id).toBe(false);
    }
  });
});

describe('F5 — helper menu-config', () => {
  it('menuAppsForIds menyaring sesuai app yang boleh dilihat role', () => {
    const filtered = menuAppsForIds(['production', 'quality']);

    expect(filtered.map((app) => app.id)).toEqual(['production', 'quality']);
    expect(menuAppsForIds([])).toEqual([]);
  });

  it('resolveMenuTarget: disabled → null, enabled → path', () => {
    expect(resolveMenuTarget({ id: 'x', label: 'X', path: '/x' })).toBe('/x');
    expect(resolveMenuTarget({ id: 'x', label: 'X', disabled: true, hint: 'h' })).toBeNull();
    expect(resolveMenuTarget({ id: 'x', label: 'X' })).toBeNull();
  });

  it('findActiveMenuPath mengenali sub-route (mis. /production/qc/42)', () => {
    const production = MENU_APPS.find((app) => app.id === 'production')!;

    expect(findActiveMenuPath(production, '/production/qc')).toBe('/production/qc');
    expect(findActiveMenuPath(production, '/production/qc/42')).toBe('/production/qc');
    expect(findActiveMenuPath(production, '/inventory/products')).toBeUndefined();
  });
});
