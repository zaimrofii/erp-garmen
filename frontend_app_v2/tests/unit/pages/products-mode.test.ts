import { readFileSync } from 'node:fs';
import path from 'node:path';
import { createElement, type ReactElement } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ProductsPage } from '@/pages/master/ProductsPage';
import { attrsOf, htmlOf } from '../../helpers/react-tree';

/**
 * FASE K3 - halaman master Products `/master/products`: mode GRID via `ViewToggle`
 * (preferensi `localStorage['mes-view-products']`), sedangkan mode `list` tetap tabel
 * dense + pagination H1.1 (TIDAK diubah). PartnersPage diperiksa di sini juga karena
 * pola grid-nya sama (ikon pengganti, bukan gambar).
 */

const ROOT = path.resolve(import.meta.dirname, '../../..');

function read(relative: string): string {
  return readFileSync(path.join(ROOT, relative), 'utf8');
}

const PAGE = read('src/pages/master/ProductsPage.tsx');
const PARTNERS = read('src/pages/master/PartnersPage.tsx');
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
      { initialEntries: ['/master/products'] },
      createElement(
        Routes,
        null,
        createElement(Route, { path: '/master/products', element: createElement(ProductsPage) }),
      ),
    ),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('FASE K3 - ProductsPage/PartnersPage: mode grid', () => {
  it('tanpa preferensi: mode GRID (mode pertama) aktif, tabel tidak dirender', () => {
    const tree = renderPage();
    const html = htmlOf(tree);

    expect(attrsOf(tree, 'aria-pressed')).toEqual(['true', 'false']);
    expect(html).not.toContain('<table');
    expect(html).toContain('Belum ada produk');
  });

  it('preferensi `list`: tabel dense aktif (tanpa kartu grid)', () => {
    stubStorage('list');

    const tree = renderPage();
    const html = htmlOf(tree);

    expect(attrsOf(tree, 'aria-pressed')).toEqual(['false', 'true']);
    expect(html).toContain('<table');
    expect(html).not.toContain('data-grid-image-fallback');
  });

  it('wiring grid produk: GridCard + image_display_url + storageKey products', () => {
    expect(PAGE).toContain('import { GridCard } from "@/components/molecules/GridCard"');
    // K5.5 — kartu memakai `image_display_url` (unggahan menang atas image_url legacy).
    expect(PAGE).toContain('imageUrl={row.image_display_url}');
    expect(PAGE).toContain('storageKey={VIEW_STORAGE_KEYS.products}');
    expect(PAGE).toContain('const MODES: readonly ViewMode[] = ["grid", "list"]');
    expect(PAGE).toContain('grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6');
  });

  it('mode list H1.1 tetap utuh: DenseTable + PaginationBar + Export CSV', () => {
    expect(PAGE).toContain('<DenseTable');
    expect(PAGE).toContain('<PaginationBar');
    expect(PAGE).toContain('exportCsv(rows, "master-products.csv", CSV_COLUMNS)');
    expect(APP).toContain('path="/master/products"');
  });

  it('PartnersPage: pola grid sama (ikon pengganti Users) & route tidak berubah', () => {
    expect(PARTNERS).toContain('import { GridCard } from "@/components/molecules/GridCard"');
    expect(PARTNERS).toContain('fallbackIcon={Users}');
    expect(PARTNERS).toContain('storageKey={VIEW_STORAGE_KEYS.partners}');
    expect(PARTNERS).toContain('const MODES: readonly ViewMode[] = ["grid", "list"]');
    expect(PARTNERS).toContain('<DenseTable');
    // K5.5 — kartu partner juga memakai gambar unggahan (image_display_url).
    expect(PARTNERS).toContain('imageUrl={row.image_display_url}');
    expect(APP).toContain('path="/master/partners"');
  });
});

describe('K5.5 — URL media di mode grid (wiring)', () => {
  it('GridCard & ImageUpload me-resolve URL media lewat lib/media-url', () => {
    expect(read('src/components/molecules/GridCard.tsx')).toContain('mediaUrl(imageUrl)');
    expect(read('src/components/molecules/ImageUpload.tsx')).toContain('mediaUrl(currentUrl)');
    expect(read('src/lib/media-url.ts')).toContain('readApiBaseUrl');
  });

  it('tanpa proxy Vite `/media` (502 di lingkungan bun) — resolusi lewat helper', () => {
    expect(read('vite.config.ts')).not.toContain("'/media'");
    expect(read('src/lib/media-url.ts')).toContain('mediaOrigin');
  });
});
