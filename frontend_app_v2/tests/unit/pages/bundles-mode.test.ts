import { readFileSync } from 'node:fs';
import path from 'node:path';
import { createElement, type ReactElement } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { BundleListPage } from '@/pages/bundles/BundleListPage';
import { attrsOf, htmlOf, textOf } from '../../helpers/react-tree';

/**
 * FASE K3 - halaman Bundle `/bundles`: mode KANBAN hidup di halaman LAMA (tanpa route
 * baru). Dua lapis pengujian (tanpa jsdom):
 *
 *   1. RENDER `react-dom/server` + `QueryClientProvider`/`MemoryRouter` - membuktikan
 *      mode tersimpan di `localStorage['mes-view-bundles']` benar-benar dipakai;
 *   2. SUMBER: wiring kanban (hook K2, `KanbanBoard`, aksi state machine) & kontrak F13
 *      yang TIDAK berubah.
 */

const ROOT = path.resolve(import.meta.dirname, '../../..');

function read(relative: string): string {
  return readFileSync(path.join(ROOT, relative), 'utf8');
}

const PAGE = read('src/pages/bundles/BundleListPage.tsx');
const APP = read('src/App.tsx');

function stubStorage(value: string | null): void {
  vi.stubGlobal('localStorage', { getItem: () => value, setItem: () => undefined });
}

function renderPage(): ReactElement {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });

  return createElement(
    QueryClientProvider,
    { client },
    createElement(
      MemoryRouter,
      { initialEntries: ['/bundles'] },
      createElement(Routes, null, createElement(Route, { path: '/bundles', element: createElement(BundleListPage) })),
    ),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('FASE K3 - BundleListPage: mode tampilan', () => {
  it('tanpa preferensi tersimpan: mode `list` (kontrak F13) yang aktif', () => {
    const tree = renderPage();

    expect(textOf(tree)).toContain('Daftar Bundle');
    expect(attrsOf(tree, 'aria-pressed')).toEqual(['true', 'false']);
    expect(htmlOf(tree)).not.toContain('data-kanban-columns');
  });

  it('preferensi `kanban` di localStorage: papan yang dipilih, daftar F13 tidak dirender', () => {
    stubStorage('kanban');

    const tree = renderPage();

    // PRA-0A.1 (K3) — MODES = ["kanban","list"]: mode pertama (kanban) aktif.
    expect(attrsOf(tree, 'aria-pressed')).toEqual(['true', 'false']);
    expect(htmlOf(tree)).not.toContain('<ul');
  });

  it('wiring kanban: hook K2 + KanbanBoard + aksi state machine, TANPA route baru', () => {
    expect(PAGE).toMatch(
      /import \{\s*bundlesKanbanQueryKey,\s*useBundlesKanban,?\s*\} from "@\/hooks\/useBundlesKanban"/,
    );
    expect(PAGE).toContain('import { KanbanBoardWithConfirm } from "@/components/molecules/KanbanBoard"');
    expect(PAGE).toContain('import { submitBundleAction } from "@/api/bundles"');
    expect(PAGE).toContain('storageKey={VIEW_STORAGE_KEYS.bundles}');
    expect(PAGE).toContain('useBundlesKanban(KANBAN_PARAMS, isKanban)');
    expect(APP).toContain('path="/bundles"');
    expect(APP).not.toContain('path="/bundles/kanban');
  });

  it('kontrak F13 tetap utuh (list, paginasi "Muat lebih banyak", form bundle)', () => {
    expect(PAGE).toContain('import { useBundles } from "@/hooks/useBundles"');
    expect(PAGE).toContain('Muat lebih banyak');
    expect(PAGE).toContain('/production/bundles/new');
    expect(PAGE).toContain('Gagal memuat daftar bundle.');
  });

  it('transisi tidak valid: toast error dari `onInvalidMove`, TANPA optimistic update', () => {
    expect(PAGE).toContain('onInvalidMove={(invalid) => {');
    expect(PAGE).toContain('setMoveError(invalid.reason)');
    expect(PAGE).toContain('title="Perpindahan tidak valid"');
    expect(PAGE).toContain('tone="error"');
    expect(PAGE).toContain('onErrorMessage: (message) => setMoveError(message)');
    expect(PAGE).not.toContain('setQueryData');
  });
});
