import { readFileSync } from 'node:fs';
import path from 'node:path';
import { createElement } from 'react';
import { describe, expect, it } from 'vitest';
import { PrintTagButton } from '@/components/molecules/PrintTagButton';
import { attrOf, htmlOf, textOf } from '../../helpers/react-tree';

/**
 * F14 — `PrintTagButton` sudah lewat adapter baru (`@/api/print`), jalur legacy dihapus.
 *
 * Rendering memakai `react-dom/server` (TANPA DOM — `.clinerules` §ENVIRONMENT) lewat
 * `createElement` (file tes ini `.ts`, jadi tanpa JSX). Komponen ini tidak butuh Provider
 * (`useApiClient` = `useMemo` + config) sehingga markup-nya bisa dirender sungguhan;
 * handler internal TIDAK diuji lewat DOM (jsdom tidak ada) — jalur cetaknya diuji di
 * `tests/unit/api/print.test.ts` + LIVE (`tests/live/f6-live.test.ts`), sedangkan wiring
 * komponen dipaku dengan pemindaian sumber seperti pola tes lain di repo ini.
 */

const ROOT = path.resolve(import.meta.dirname, '../../..');

function read(relative: string): string {
  return readFileSync(path.join(ROOT, relative), 'utf8');
}

const SOURCE = read('src/components/molecules/PrintTagButton.tsx');

describe('F14 — PrintTagButton (render)', () => {
  it('merender tombol "Cetak Tag" + ikon printer (komponen dieksekusi React)', () => {
    const tree = createElement(PrintTagButton, { bundleId: '16' });
    const html = htmlOf(tree);

    expect(textOf(tree)).toContain('Cetak Tag');
    expect(html).toContain('<button');
    expect(html).toContain('lucide-printer');
    // Toast tertutup → AnimatePresence tidak merender apa pun: HANYA satu tombol di markup.
    expect(html.match(/<button/g)?.length).toBe(1);
    // ... tetapi Toast memang ter-wire (dibuktikan di tes wiring di bawah).
    expect(SOURCE).toContain('open={toast !== null}');
  });

  it('props `disabled` + `className` diteruskan (kontrak props tidak berubah)', () => {
    const tree = createElement(PrintTagButton, {
      bundleId: '1',
      disabled: true,
      className: 'mb-4',
    });
    const html = htmlOf(tree);

    expect(html).toContain('disabled');
    expect(attrOf(tree, 'class')).toContain('mb-4');
  });
});

describe('F14 — PrintTagButton (wiring adapter)', () => {
  it('mengimpor printBundleTag dari @/api/print, BUKAN jalur legacy', () => {
    expect(SOURCE).toContain("import { printBundleTag } from '@/api/print'");
    expect(SOURCE).not.toContain("from '@/integrations/print-tag'");
    expect(SOURCE).not.toContain("from '../integrations/print-tag'");
  });

  it('memanggil printBundleTag(client, bundleId) + menangani error (Toast + onError)', () => {
    expect(SOURCE).toContain('await printBundleTag(client, bundleId)');
    expect(SOURCE).toContain('catch (caught)');
    expect(SOURCE).toContain('caught instanceof Error ? caught.message');
    expect(SOURCE).toContain("setToast({ tone: 'error', title: 'Gagal mencetak tag'");
    expect(SOURCE).toContain('onError?.(message)');
    expect(SOURCE).toContain('onSuccess?.()');
    expect(SOURCE).toContain('<Toast');
  });

  it('sukses memakai bytes/backend dari response §7.1 & barrel mengekspor adapter', () => {
    expect(SOURCE).toContain('${job.bytes} bytes, backend ${job.backend}');

    const barrel = read('src/api/print.ts');

    expect(barrel).toContain("printBundleTag = pickAdapter('print'");
    expect(barrel).toContain('PRINT_BUNDLE_TAG_PATH');
  });
});
