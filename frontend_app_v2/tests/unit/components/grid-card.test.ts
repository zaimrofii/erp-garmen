import { createElement } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { GridCard } from '@/components/molecules/GridCard';
import { findElement, htmlOf, textOf } from '../../helpers/react-tree';

afterEach(() => {
  vi.unstubAllEnvs();
});

/**
 * FASE K3 - `GridCard` (mode grid halaman master).
 *
 * Tanpa jsdom: komponen dipanggil langsung (tanpa hook) → handler klik & atribut
 * gambar diperiksa dari pohon element + HTML `react-dom/server`.
 */

describe('FASE K3 - GridCard', () => {
  it('tanpa gambar: kotak ikon pengganti (bukan <img>)', () => {
    const tree = GridCard({ title: 'Kaos Polos', subtitle: 'TS-900 · PCS', imageUrl: null });
    const html = htmlOf(tree);

    expect(html).toContain('data-grid-image-fallback="Kaos Polos"');
    expect(html).not.toContain('<img');
    expect(textOf(tree)).toContain('Kaos Polos');
    expect(textOf(tree)).toContain('TS-900 · PCS');
  });

  it('image_url terisi: <img> dengan alt kosong (dekoratif)', () => {
    const tree = GridCard({
      title: 'Kaos Polos',
      imageUrl: 'https://cdn.klien.com/kaos.png',
    });

    expect(htmlOf(tree)).toContain('src="https://cdn.klien.com/kaos.png"');
    expect(htmlOf(tree)).toContain('alt=""');
    expect(htmlOf(tree)).not.toContain('data-grid-image-fallback');
  });

  it('image_url kosong/spasi: kembali ke ikon pengganti', () => {
    const blank = GridCard({ title: 'Kaos Polos', imageUrl: '   ' });

    expect(htmlOf(blank)).toContain('data-grid-image-fallback="Kaos Polos"');
  });

  it('badges dirender di bawah judul', () => {
    const tree = GridCard({
      title: 'Kaos Polos',
      badges: createElement('span', null, 'AKTIF'),
    });

    expect(textOf(tree)).toContain('AKTIF');
  });

  it('onClick: tombol aksesibel memanggil handler', () => {
    const onClick = vi.fn();
    const tree = GridCard({ title: 'Kaos Polos', onClick });

    const button = findElement(
      tree,
      (element) => element.props['aria-label'] === 'Buka Kaos Polos',
    );
    expect(button).toBeDefined();

    const handler = button?.props['onClick'];
    expect(typeof handler).toBe('function');
    (handler as () => void)();

    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it('tanpa onClick: tidak ada tombol (kartu hanya informasi)', () => {
    const tree = GridCard({ title: 'Kaos Polos' });

    expect(
      findElement(tree, (element) => element.props['aria-label'] === 'Buka Kaos Polos'),
    ).toBeUndefined();
  });
});

describe('K5.5 — resolusi URL media di GridCard', () => {
  it('URL relatif `/media/...` di-prefix origin backend dari VITE_API_BASE_URL', () => {
    vi.stubEnv('VITE_API_BASE_URL', 'http://localhost:8000/api/v1');

    const tree = GridCard({
      title: 'Kaos Polos',
      imageUrl: '/media/products/2026/10/kaos.jpg',
    });

    expect(htmlOf(tree)).toContain(
      'src="http://localhost:8000/media/products/2026/10/kaos.jpg"',
    );
  });
});
