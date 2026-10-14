import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it, vi } from 'vitest';
import { AppMenuBar } from '@/components/organisms/AppMenuBar';
import { NAV_APPS } from '@/app/nav-config';
import { findMenuItemPath, isMenuItemActive, type MenuItem } from '@/app/menu-config';
import { attrOf, attrsOf, callProp, findElement, htmlOf, textOf, walk } from '../../helpers/react-tree';

/**
 * F16 — `AppMenuBar` = menu DALAM app aktif (fix F5: dulu menerima `menus: MenuApp[]`
 * berisi DAFTAR APP sehingga TopBar menduplikasi Sidebar).
 *
 * Aturan yang diuji:
 *  - item tanpa `children` → LINK (`<button role="menuitem">`), bukan dropdown;
 *  - item dengan `children` → `<Dropdown>` dengan isi anak-anaknya;
 *  - `currentPath` menentukan highlight (`aria-current="page"` / `activeId`);
 *  - klik memicu `onNavigate(path)`.
 *
 * Komponen TANPA hook ⇒ dipanggil langsung (pola F5/ChatterBox, tanpa DOM).
 */

const ROOT = path.resolve(import.meta.dirname, '../../..');

function inventoryTopbar(): readonly MenuItem[] {
  return NAV_APPS.find((app) => app.id === 'inventory')?.topbar ?? [];
}

function renderItem(items: readonly MenuItem[], currentPath: string) {
  const onNavigate = vi.fn();

  return { tree: AppMenuBar({ items, currentPath, onNavigate }), onNavigate };
}

/** Semua link (`<button>`) di baris ini + label & `aria-current`-nya. */
function links(tree: unknown): { label: string; current: string | undefined }[] {
  const found: { label: string; current: string | undefined }[] = [];

  walk(tree as never, (element) => {
    if (element.type !== 'button') return;

    found.push({
      label: String(element.props['children'] ?? ''),
      current: element.props['aria-current'] as string | undefined,
    });
  });

  return found;
}

describe('F16 — item tanpa children dirender LINK (bukan dropdown)', () => {
  it('4 menu Inventory jadi 4 link, tanpa satu pun dropdown', () => {
    const { tree } = renderItem(inventoryTopbar(), '/inventory/products');

    expect(attrOf(tree, 'data-app-menu-bar')).toBe('true');
    expect(attrOf(tree, 'role')).toBe('menubar');
    // tidak ada trigger dropdown sama sekali
    expect(attrsOf(tree, 'data-dropdown-trigger')).toEqual([]);

    const text = textOf(tree);
    for (const label of ['Products', 'Operations', 'Reporting', 'Configuration']) {
      expect(text, label).toContain(label);
    }
    // Daftar APP (duplikat Sidebar) TIDAK lagi muncul di baris ini: yang dirender
    // PERSIS label topbar app aktif. Dibandingkan sebagai LABEL UTUH, bukan
    // substring — label menu master sah memuat nama app (mis. H1.8 "Master
    // Production Line"), sementara "Production" sebagai item app tetap dilarang.
    const rendered = links(tree).map((item) => item.label);
    expect(rendered).toEqual(inventoryTopbar().map((item) => item.label));
    for (const app of NAV_APPS) {
      expect(rendered, app.label).not.toContain(app.label);
    }
  });

  it('path aktif diberi `aria-current="page"` (hanya satu)', () => {
    const { tree } = renderItem(inventoryTopbar(), '/inventory/operations');

    expect(
      links(tree)
        .filter((item) => item.current === 'page')
        .map((item) => item.label),
    ).toEqual(['Operations']);
  });

  it('sub-route ikut dianggap aktif (mis. /inventory/products/42)', () => {
    const { tree } = renderItem(inventoryTopbar(), '/inventory/products/42');

    expect(links(tree).filter((item) => item.current === 'page')).toEqual([
      { label: 'Products', current: 'page' },
    ]);
  });

  it('klik link memicu onNavigate dengan path item', () => {
    const { tree, onNavigate } = renderItem(inventoryTopbar(), '/inventory/products');
    const reporting = findElement(
      tree as never,
      (candidate) => candidate.type === 'button' && candidate.props['children'] === 'Reporting',
    );

    callProp(reporting!, 'onClick');

    expect(onNavigate).toHaveBeenCalledTimes(1);
    expect(onNavigate).toHaveBeenCalledWith('/inventory/reporting');
  });

  it('items kosong → nav kosong (app tanpa topbar, mis. Dashboard/AI)', () => {
    const { tree } = renderItem([], '/');

    expect(attrOf(tree, 'data-app-menu-bar')).toBe('true');
    expect(htmlOf(tree)).not.toContain('<button');
  });
});

describe('F16 — item dengan children dirender DROPDOWN', () => {
  const items: readonly MenuItem[] = [
    {
      label: 'Products',
      path: '/inventory/products',
      children: [
        { label: 'List', path: '/inventory/products' },
        { label: 'New', path: '/inventory/products/new' },
      ],
    },
    { label: 'Operations', path: '/inventory/operations' },
  ];

  it('satu dropdown (labels anak = isi menu) + satu link', () => {
    const { tree } = renderItem(items, '/inventory/products');
    const dropdown = findElement(tree as never, (item) => item.props['label'] === 'Products');

    expect(dropdown?.props['items']).toEqual([
      { id: '/inventory/products', label: 'List' },
      { id: '/inventory/products/new', label: 'New' },
    ]);
    expect(attrsOf(tree, 'data-dropdown-trigger')).toEqual(['Products']);
    expect(textOf(tree)).toContain('Operations');
  });

  it('anak yang aktif jadi `activeId`; pilih anak → onNavigate(path anak)', () => {
    const { tree, onNavigate } = renderItem(items, '/inventory/products/new');
    const dropdown = findElement(tree as never, (item) => item.props['label'] === 'Products');

    expect(dropdown?.props['activeId']).toBe('/inventory/products/new');

    callProp(dropdown!, 'onSelect', '/inventory/products/new');

    expect(onNavigate).toHaveBeenCalledWith('/inventory/products/new');
  });

  it('id tak dikenal diabaikan (tidak throw, tidak navigate)', () => {
    const { tree, onNavigate } = renderItem(items, '/inventory/products');
    const dropdown = findElement(tree as never, (item) => item.props['label'] === 'Products');

    expect(() => callProp(dropdown!, 'onSelect', 'tidak-ada')).not.toThrow();
    expect(onNavigate).not.toHaveBeenCalled();
  });
});

describe('F16 — helper menu aktif (menu-config)', () => {
  it('findMenuItemPath: item sendiri, anaknya, atau undefined', () => {
    const item: MenuItem = {
      label: 'Products',
      path: '/inventory/products',
      children: [{ label: 'New', path: '/inventory/products/new' }],
    };

    expect(findMenuItemPath(item, '/inventory/products')).toBe('/inventory/products');
    expect(findMenuItemPath(item, '/inventory/products/new')).toBe('/inventory/products/new');
    expect(findMenuItemPath(item, '/inventory/operations')).toBeUndefined();
    expect(isMenuItemActive(item, '/inventory/products/42')).toBe(true);
    expect(isMenuItemActive(item, '/purchase/orders')).toBe(false);
  });

  it('data nyata NAV_APPS: production/settings juga jadi menu dalam-app', () => {
    const production = NAV_APPS.find((app) => app.id === 'production')?.topbar ?? [];
    const { tree } = renderItem(production, '/production/qc');

    expect(textOf(tree)).toContain('Shop Floor');
    expect(textOf(tree)).toContain('QC');
    expect(links(tree).filter((item) => item.current === 'page').map((item) => item.label)).toEqual([
      'QC',
    ]);
  });
});

describe('F16 — TopBar memakai menu APP AKTIF (bukan daftar app)', () => {
  const source = readFileSync(path.join(ROOT, 'src/app/layouts/TopBar.tsx'), 'utf8');

  it('mengambil `app.topbar` dan mengirim sebagai `items`', () => {
    expect(source).toContain('const items = app?.topbar ?? [];');
    expect(source).toContain('<AppMenuBar items={items}');
  });

  it('TIDAK lagi memakai daftar app (menuAppsForIds/useVisibleApps)', () => {
    expect(source).not.toContain('menuAppsForIds');
    expect(source).not.toContain('useVisibleApps');
    expect(source).not.toContain('menus={');
  });

  it('signature TopBar tidak berubah (app, currentPath, onNavigate)', () => {
    expect(source).toContain('app: NavApp | undefined;');
    expect(source).toContain('currentPath: string;');
    expect(source).toContain('onNavigate: (path: string) => void;');
  });
});
