import { createElement } from 'react';
import { describe, expect, it } from 'vitest';
import { Dropdown, type DropdownItem } from '@/components/atoms/Dropdown';
import {
  firstEnabledIndex,
  isCloseKey,
  resolveSelection,
  stepFocusIndex,
  stepForKey,
} from '@/lib/dropdown-state';
import { attrOf, attrsOf, htmlOf, textOf } from '../../helpers/react-tree';

/**
 * F5 — atom `Dropdown`.
 *
 * CATATAN GAYA (aturan repo): `react-dom/server` + walker, TANPA DOM/jsdom.
 * Efek & interaksi klik tidak berjalan di SSR, jadi:
 *  - struktur/atribut ARIA diuji dari HTML hasil render (termasuk state terbuka via
 *    seam `defaultOpen`);
 *  - logika keyboard & pemilihan item diuji lewat helper MURNI `@/lib/dropdown-state`
 *    (fungsi yang benar-benar dipanggil atom).
 */

const ITEMS: DropdownItem[] = [
  { id: '/production/scan', label: 'Shop Floor' },
  { id: '/production/buffer-queue', label: 'Buffer Queue', disabled: true, hint: 'belum ada halaman' },
  { id: '/production/routing', label: 'Routing' },
];

describe('F5 — helper murni dropdown-state', () => {
  it('firstEnabledIndex melewati item disabled', () => {
    expect(firstEnabledIndex([])).toBe(-1);
    expect(firstEnabledIndex([{ disabled: true }, { disabled: true }])).toBe(-1);
    expect(firstEnabledIndex([{ disabled: true }, {}])).toBe(1);
    expect(firstEnabledIndex(ITEMS)).toBe(0);
  });

  it('stepFocusIndex wrap + lewati disabled', () => {
    expect(stepFocusIndex(ITEMS, 0, 1)).toBe(2); // index 1 disabled
    expect(stepFocusIndex(ITEMS, 2, 1)).toBe(0); // wrap
    expect(stepFocusIndex(ITEMS, 0, -1)).toBe(2);
    expect(stepFocusIndex([], 0, 1)).toBe(-1);
    expect(stepFocusIndex([{ disabled: true }], 0, 1)).toBe(-1);
  });

  it('isCloseKey & stepForKey', () => {
    expect(isCloseKey('Escape')).toBe(true);
    expect(isCloseKey('Enter')).toBe(false);
    expect(stepForKey('ArrowDown')).toBe(1);
    expect(stepForKey('ArrowUp')).toBe(-1);
    expect(stepForKey('Tab')).toBe(0);
  });

  it('resolveSelection menolak item disabled & index di luar batas', () => {
    expect(resolveSelection(ITEMS, 0)).toBe('/production/scan');
    expect(resolveSelection(ITEMS, 1)).toBeNull();
    expect(resolveSelection(ITEMS, 9)).toBeNull();
    expect(resolveSelection([], 0)).toBeNull();
  });
});

describe('F5 — Dropdown tertutup (SSR default)', () => {
  const tree = createElement(Dropdown, { label: 'Production', items: ITEMS });

  it('trigger accessible: haspopup + aria-expanded=false', () => {
    expect(attrOf(tree, 'aria-haspopup')).toBe('menu');
    expect(attrOf(tree, 'aria-expanded')).toBe('false');
    expect(attrOf(tree, 'data-dropdown-trigger')).toBe('Production');
  });

  it('menu TIDAK dirender saat tertutup', () => {
    expect(htmlOf(tree)).not.toContain('role="menu"');
    expect(attrsOf(tree, 'data-menu-item')).toEqual([]);
  });
});

describe('F5 — Dropdown terbuka (seam defaultOpen)', () => {
  const tree = createElement(Dropdown, {
    label: 'Production',
    items: ITEMS,
    activeId: '/production/routing',
    defaultOpen: true,
  });

  it('aria-expanded=true + role=menu + aria-controls terpasang', () => {
    expect(attrOf(tree, 'aria-expanded')).toBe('true');
    expect(htmlOf(tree)).toContain('role="menu"');
    expect(attrOf(tree, 'aria-controls')).toBeDefined();
  });

  it('semua item dirender dengan urutan & id stabil (key = id)', () => {
    expect(attrsOf(tree, 'data-menu-item')).toEqual([
      '/production/scan',
      '/production/buffer-queue',
      '/production/routing',
    ]);
    expect(textOf(tree)).toContain('Shop Floor');
  });

  it('item aktif ditandai aria-current + highlight token', () => {
    expect(attrOf(tree, 'aria-current')).toBe('page');
    expect(htmlOf(tree)).toContain('bg-primary text-primary-foreground');
  });

  it('item disabled: atribut disabled + aria-disabled + hint tampil', () => {
    const html = htmlOf(tree);

    expect(html).toContain('disabled=""');
    expect(html).toContain('aria-disabled="true"');
    expect(textOf(tree)).toContain('belum ada halaman');
  });

  it('fokus awal di item enabled pertama (data-focused)', () => {
    expect(attrOf(tree, 'data-focused')).toBe('true');
  });

  it('OKLCH-only: tidak ada hex/rgb di HTML, ring focus-visible ada', () => {
    const html = htmlOf(tree);

    expect(html).not.toMatch(/#[0-9a-f]{3,8}\b/i);
    expect(html).not.toMatch(/rgba?\(/i);
    expect(html).toContain('focus-visible:ring-2');
  });
});
