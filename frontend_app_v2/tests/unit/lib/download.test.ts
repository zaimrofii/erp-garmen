import { describe, expect, it } from 'vitest';
import { downloadBlob, readFilenameFromDisposition } from '@/lib/download';

/**
 * H4.8 - helper unduhan (`lib/download.ts`).
 *
 * Lingkungan test = `node` (tanpa DOM), jadi dependensi DOM **disuntikkan**:
 * `createObjectURL`/`revokeObjectURL`/`document` palsu → urutan aksi (buat URL →
 * klik `<a download>` → bersihkan) bisa diverifikasi tanpa jsdom.
 */

interface FakeAnchor {
  href: string;
  download: string;
  rel: string;
  clicked: number;
  removed: number;
}

function fakeDocument() {
  const anchors: FakeAnchor[] = [];
  const appended: FakeAnchor[] = [];
  const documentRef = {
    createElement: (_tag: string) => {
      const anchor: FakeAnchor = {
        href: '',
        download: '',
        rel: '',
        clicked: 0,
        removed: 0,
      };
      const node = {
        get href() {
          return anchor.href;
        },
        set href(value: string) {
          anchor.href = value;
        },
        get download() {
          return anchor.download;
        },
        set download(value: string) {
          anchor.download = value;
        },
        get rel() {
          return anchor.rel;
        },
        set rel(value: string) {
          anchor.rel = value;
        },
        click() {
          anchor.clicked += 1;
        },
        remove() {
          anchor.removed += 1;
        },
      };
      anchors.push(anchor);
      return node;
    },
    body: {
      appendChild: (node: unknown) => {
        appended.push(node as FakeAnchor);
        return node;
      },
    },
  } as unknown as Document;

  return { documentRef, anchors, appended };
}

describe('H4.8 - readFilenameFromDisposition', () => {
  it('membaca filename polos, terkuotasi, dan RFC 5987 `filename*`', () => {
    expect(readFilenameFromDisposition('attachment; filename="sales-2026-10.xlsx"')).toBe(
      'sales-2026-10.xlsx',
    );
    expect(readFilenameFromDisposition('attachment; filename=purchases-2026-Q4.pdf')).toBe(
      'purchases-2026-Q4.pdf',
    );
    expect(
      readFilenameFromDisposition("attachment; filename*=UTF-8''stok%20oktober.xlsx"),
    ).toBe('stok oktober.xlsx');
  });

  it('`null`/kosong/tanpa filename → null (pemanggil memakai nama fallback)', () => {
    expect(readFilenameFromDisposition(null)).toBeNull();
    expect(readFilenameFromDisposition('')).toBeNull();
    expect(readFilenameFromDisposition('attachment')).toBeNull();
    expect(readFilenameFromDisposition('attachment; filename=""')).toBeNull();
  });
});

describe('H4.8 - downloadBlob', () => {
  it('membuat URL, klik `<a download>` sementara, lalu revoke (tanpa sisa DOM)', () => {
    const created: Blob[] = [];
    const revoked: string[] = [];
    const { documentRef, anchors, appended } = fakeDocument();

    const url = downloadBlob(new Blob(['x']), 'sales-2026-10.xlsx', {
      createObjectURL: (blob) => {
        created.push(blob);
        return 'blob:mes-1';
      },
      revokeObjectURL: (value) => {
        revoked.push(value);
      },
      document: documentRef,
    });

    expect(url).toBe('blob:mes-1');
    expect(created).toHaveLength(1);
    expect(anchors[0].href).toBe('blob:mes-1');
    expect(anchors[0].download).toBe('sales-2026-10.xlsx');
    expect(anchors[0].rel).toBe('noopener');
    expect(anchors[0].clicked).toBe(1);
    expect(anchors[0].removed).toBe(1);
    expect(appended).toHaveLength(1);
    expect(revoked).toEqual(['blob:mes-1']);
  });
});
