import { readdirSync, readFileSync, statSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

/**
 * F12/12.4 — AUDIT a11y: tombol ikon tanpa nama aksesibel.
 *
 * Dua bentuk yang diuji berbasis SUMBER (tanpa DOM, sesuai `.clinerules`):
 *  1. `<button>` yang isinya HANYA ikon/ekspresi tanpa `aria-label`;
 *  2. tombol atom `<Button icon={…} />` (self-closing) tanpa `aria-label` — ini bentuk paling
 *     mudah luput karena ikonnya datang dari prop, bukan dari children.
 *
 * `ALLOWED_DYNAMIC_TEXT` = blok yang teksnya DINAMIS (dari props/ternary) sehingga tidak
 * terlihat oleh pemeriksa berbasis teks; sudah ditinjau manual: namanya ADA saat runtime.
 */

const ROOT = path.resolve(import.meta.dirname, '../../..');
const SRC = path.join(ROOT, 'src');

function walk(dir: string): string[] {
  const out: string[] = [];

  for (const entry of readdirSync(dir)) {
    const full = path.join(dir, entry);

    if (statSync(full).isDirectory()) out.push(...walk(full));
    else if (full.endsWith('.tsx')) out.push(full);
  }

  return out;
}

/** Blok `<button>…</button>` tanpa teks terlihat & tanpa `aria-label`. */
function iconOnlyButtons(source: string): string[] {
  const found: string[] = [];

  for (const match of source.matchAll(/<button[\s\S]*?<\/button>/g)) {
    const block = match[0];
    const openEnd = block.indexOf('>');
    const openTag = block.slice(0, openEnd + 1);

    if (openTag.includes('aria-label')) continue;

    const inner = block.slice(openEnd + 1, block.lastIndexOf('</button>'));
    const text = inner
      .replace(/\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}/g, ' ')
      .replace(/<[^>]*>/g, ' ')
      .replace(/\s+/g, ' ')
      .trim();

    if (text.length === 0) found.push(openTag.replace(/\s+/g, ' ').slice(0, 80));
  }

  return found;
}

describe('F12/12.4 — a11y tombol ikon', () => {
  const files = walk(SRC);

  it('tidak ada tombol atom `<Button icon>` tanpa anak teks & tanpa aria-label', () => {
    const offenders: string[] = [];

    for (const file of files) {
      const source = readFileSync(file, 'utf8');

      for (const match of source.matchAll(/<Button[\s\S]*?(?:\/>|<\/Button>)/g)) {
        const block = match[0];

        if (!/icon=\{/.test(block) || block.includes('aria-label')) continue;

        const inner = block.endsWith('/>')
          ? ''
          : block.slice(block.indexOf('>') + 1, block.lastIndexOf('</Button>')).trim();

        if (inner.length === 0) offenders.push(`${path.relative(SRC, file)}: ${block.slice(0, 60)}`);
      }
    }

    expect(offenders).toEqual([]);
  });

  it('tombol `<button>` tanpa teks statis hanya yang teksnya dinamis (sudah ditinjau)', () => {
    const offenders = files
      .filter((file) => iconOnlyButtons(readFileSync(file, 'utf8')).length > 0)
      .map((file) => path.relative(SRC, file).replace(/\\/g, '/'))
      .sort();

    expect(offenders).toEqual([
      // FIX ROUTE — teks tombol dari KONSTANTA yang diekspor
      // (`ACCESS_DENIED_ACTION` / `ROUTE_ERROR_BACK` / `ROUTE_ERROR_RELOAD`): tidak terlihat
      // pemeriksa berbasis teks statis, tapi ADA saat runtime (`renderToString` membuktikan).
      'app/AccessDenied.tsx',
      // komponen generik: children ditentukan pemanggil (`Button icon+children`)
      'components/atoms/Button.tsx',
      // teks dari prop `trigger` (label app di menu bar)
      'components/atoms/Dropdown.tsx',
      // FIX ROUTE — tombol fallback error boundary (teks dari konstanta di atas)
      'components/organisms/RouteErrorBoundary.tsx',
      // teks dari ternary `{save.isPending ? 'Menyimpan...' : 'Simpan'}`
      'pages/settings/RoutingConfigPage.tsx',
    ]);
  });

  it('setiap tombol ikon-saja yang MEMANG ada membawa aria-label (bukti di Dropdown/Modal)', () => {
    const dropdown = readFileSync(path.join(SRC, 'components/atoms/Dropdown.tsx'), 'utf8');
    const modal = readFileSync(path.join(SRC, 'components/atoms/Modal.tsx'), 'utf8');

    expect(dropdown).toContain('aria-haspopup="menu"');
    expect(modal).toContain('aria-label');
  });
});
