import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

/**
 * F4/4.2 — KUNCI WIRING (bukan render, bukan DOM).
 *
 * 3 halaman harus mengoper `preview` (kanonik) + menggabungkan event real-time,
 * dan tidak boleh lagi memakai alias deprecated `events`. Tes ini membaca sumber
 * halaman karena rendering halaman butuh Router + QueryClient (di luar gaya tes
 * `react-dom/server` yang dipakai repo ini).
 */

const ROOT = path.resolve(import.meta.dirname, '../../..');

const WIRED_PAGES = [
  'src/pages/bundles/BundleWorkshopPage.tsx',
  'src/pages/bundles/BundleDetailPage.tsx',
  'src/pages/production/BundleDetailPage.tsx',
];

describe('F4 — wiring chatter real-time di 3 halaman', () => {
  for (const page of WIRED_PAGES) {
    it(`${page}: useChatterWs + preview= dan tanpa alias events=`, () => {
      const source = readFileSync(path.join(ROOT, page), 'utf8');

      expect(source).toContain("useChatterWs({ resource: 'bundles'");
      expect(source).toContain('preview={mergeChatterPreview(');
      expect(source).not.toContain('events={chatter');
    });
  }

  it('ChatterBox tidak lagi punya prop alias `events`', () => {
    const source = readFileSync(
      path.join(ROOT, 'src/components/molecules/ChatterBox.tsx'),
      'utf8'
    );

    expect(source).not.toContain('events?: ChatterEvent[]');
    expect(source).not.toContain('preview ?? events');
  });
});
