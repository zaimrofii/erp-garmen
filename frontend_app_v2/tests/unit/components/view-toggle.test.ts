import { createElement, type ReactElement } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ViewToggle } from '@/components/molecules/ViewToggle';
import {
  isViewMode,
  persistViewMode,
  readViewMode,
  VIEW_MODES,
  VIEW_STORAGE_KEYS,
} from '@/lib/view-mode';
import { attrsOf, callProp, findElement, htmlOf, textOf } from '../../helpers/react-tree';

/**
 * FASE K3 - `ViewToggle` + helper `lib/view-mode`.
 *
 * CATATAN GAYA (aturan repo): `react-dom/server` + walker, TANPA DOM/jsdom. Handler
 * tombol dipanggil langsung dari pohon element (`callProp`) - bukan event browser.
 * `localStorage` diganti STUB supaya perilaku baca/tulis bisa diuji di Node.
 */

interface FakeStorage {
  value: string | null;
  getItem: (key: string) => string | null;
  setItem: (key: string, value: string) => void;
}

function stubStorage(initial: string | null): FakeStorage {
  const store: FakeStorage = {
    value: initial,
    getItem: () => store.value,
    setItem: (_key, value) => {
      store.value = value;
    },
  };
  vi.stubGlobal('localStorage', store);

  return store;
}

/** Panggil komponen sebagai FUNGSI (tanpa hook) supaya handler tombol bisa di-walk. */
function render(
  value: 'list' | 'grid' | 'kanban',
  onChange: (mode: string) => void,
  storageKey: string = VIEW_STORAGE_KEYS.bundles,
): ReactElement {
  return ViewToggle({ modes: VIEW_MODES, value, onChange, storageKey });
}

function button(tree: ReactElement, label: string): ReactElement<Record<string, unknown>> {
  const found = findElement(tree, (element) => element.props['aria-label'] === label);
  expect(found).toBeDefined();

  return found!;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('FASE K3 - ViewToggle', () => {
  it('merender satu tombol per mode + aria-pressed pada mode aktif', () => {
    const tree = render('grid', () => undefined);
    const html = htmlOf(tree);

    expect(html).toContain('Mode List');
    expect(html).toContain('Mode Grid');
    expect(html).toContain('Mode Kanban');
    expect(attrsOf(tree, 'aria-pressed')).toEqual(['false', 'true', 'false']);
    expect(attrsOf(tree, 'data-view-toggle')).toEqual([]);
  });

  it('klik mode lain: simpan ke localStorage + panggil onChange', () => {
    const store = stubStorage(null);
    const onChange = vi.fn();

    callProp(button(render('list', onChange), 'Mode Kanban'), 'onClick');

    expect(onChange).toHaveBeenCalledWith('kanban');
    expect(store.value).toBe('kanban');
  });

  it('klik mode yang sedang aktif: tetap disimpan, onChange TIDAK dipanggil', () => {
    const store = stubStorage('grid');
    const onChange = vi.fn();

    callProp(button(render('grid', onChange), 'Mode Grid'), 'onClick');

    expect(onChange).not.toHaveBeenCalled();
    expect(store.value).toBe('grid');
  });

  it('tanpa `storageKey`: onChange jalan tetapi tidak menulis storage', () => {
    const store = stubStorage(null);
    const onChange = vi.fn();
    const tree = ViewToggle({ modes: ['list', 'kanban'], value: 'list', onChange });

    callProp(button(tree, 'Mode Kanban'), 'onClick');

    expect(onChange).toHaveBeenCalledWith('kanban');
    expect(store.value).toBeNull();
  });
});

describe('FASE K3 - lib/view-mode (PURE)', () => {
  it('readViewMode menerima hanya mode yang didukung, sisanya fallback', () => {
    stubStorage('kanban');
    expect(readViewMode(VIEW_STORAGE_KEYS.bundles, ['list', 'kanban'])).toBe('kanban');

    stubStorage('grid');
    expect(readViewMode(VIEW_STORAGE_KEYS.bundles, ['list', 'kanban'])).toBe('list');

    stubStorage(null);
    expect(readViewMode(VIEW_STORAGE_KEYS.products, ['list', 'grid'])).toBe('list');
  });

  it('isViewMode menyaring nilai asing & persistViewMode aman tanpa storage', () => {
    expect(isViewMode('kanban')).toBe(true);
    expect(isViewMode('grid')).toBe(true);
    expect(isViewMode('timeline')).toBe(false);
    expect(textOf(createElement('span', null, 'ok'))).toContain('ok');

    expect(() => persistViewMode(VIEW_STORAGE_KEYS.partners, 'grid')).not.toThrow();
  });
});
