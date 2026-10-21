import { createElement } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  ImageBox,
  ImageUpload,
  type ImageBoxProps,
} from '@/components/molecules/ImageUpload';
import {
  fileFromDropEvent,
  fileFromInputEvent,
  firstFileFrom,
  IMAGE_ACCEPT,
  IMAGE_MAX_BYTES,
  pickImageFile,
  toImageFormData,
  validateImageFile,
} from '@/lib/image-upload';
import { attrOf, callProp, findElement, htmlOf, textOf } from '../../helpers/react-tree';

afterEach(() => {
  vi.unstubAllEnvs();
});

/**
 * FASE K5.3 - `ImageUpload`/`ImageBox` + `lib/image-upload` (PURE).
 *
 * TANPA jsdom (`.clinerules` §ENVIRONMENT): `ImageBox` PURE dipanggil sebagai fungsi
 * lalu handler-nya di-walk (`callProp`) dengan event tiruan; `ImageUpload` (ber-hook)
 * hanya diuji lewat `renderToString` (`htmlOf`) - jadi yang diuji adalah KEPUTUSAN
 * handler/props, bukan perilaku browser.
 */

interface FakeFile {
  name: string;
  size: number;
}

function fakeFile(name: string, size = 1024): FakeFile {
  return { name, size };
}

function realFile(name = 'kaos.jpg'): File {
  return new File([new Uint8Array([1, 2, 3])], name, { type: 'image/jpeg' });
}

function listOf(...files: File[]): { length: number; [index: number]: File } {
  const list: { length: number; [index: number]: File } = { length: files.length };
  files.forEach((file, index) => {
    list[index] = file;
  });

  return list;
}

describe('K5.3 — validateImageFile (PURE)', () => {
  it('jpg/jpeg/png/webp dalam batas 5 MB → valid', () => {
    for (const name of ['kaos.jpg', 'kaos.JPEG', 'toko.png', 'toko.webp']) {
      expect(validateImageFile(fakeFile(name)), name).toEqual({ ok: true });
    }
  });

  it('ekstensi di luar whitelist (gif) → pesan format', () => {
    const verdict = validateImageFile(fakeFile('animasi.gif'));

    expect(verdict.ok).toBe(false);
    expect(verdict.ok ? '' : verdict.error).toContain('Format tidak didukung');
  });

  it('berkas di atas 5 MB ditolak, berkas 0 byte ditolak', () => {
    const big = validateImageFile(fakeFile('besar.jpg', IMAGE_MAX_BYTES + 1));
    expect(big.ok ? '' : big.error).toContain('5 MB');

    expect(validateImageFile(fakeFile('kosong.jpg', 0))).toEqual({
      ok: false,
      error: 'Berkas kosong.',
    });
  });

  it('tanpa berkas → pesan "tidak ada berkas"', () => {
    expect(validateImageFile(null)).toEqual({
      ok: false,
      error: 'Tidak ada berkas yang dipilih.',
    });
  });
});

describe('K5.3 — pickImageFile (PURE)', () => {
  it('berkas sah → onAccept dipanggil sekali, tanpa onReject', () => {
    const onAccept = vi.fn();
    const onReject = vi.fn();
    const file = realFile('kaos.png');

    expect(pickImageFile(file, { onAccept, onReject })).toBe('accepted');
    expect(onAccept).toHaveBeenCalledWith(file);
    expect(onReject).not.toHaveBeenCalled();
  });

  it('gif/berkas terlalu besar → onReject dipanggil, onAccept TIDAK (tanpa upload)', () => {
    const onAccept = vi.fn();
    const onReject = vi.fn();

    expect(pickImageFile(realFile('animasi.gif'), { onAccept, onReject })).toBe('rejected');
    expect(onAccept).not.toHaveBeenCalled();
    expect(onReject).toHaveBeenCalledTimes(1);
  });

  it('tidak ada berkas → "empty" (handler tidak dipanggil)', () => {
    const onAccept = vi.fn();
    const onReject = vi.fn();

    expect(pickImageFile(null, { onAccept, onReject })).toBe('empty');
    expect(onAccept).not.toHaveBeenCalled();
    expect(onReject).not.toHaveBeenCalled();
  });
});

describe('K5.3 — pembaca berkas & FormData (PURE)', () => {
  it('firstFileFrom: elemen pertama dipakai, list kosong/asing → null', () => {
    const file = realFile();

    expect(firstFileFrom(listOf(file))).toBe(file);
    expect(firstFileFrom({ length: 0 })).toBeNull();
    expect(firstFileFrom(undefined)).toBeNull();
    expect(firstFileFrom({ length: '2' })).toBeNull();
  });

  it('fileFromInputEvent & fileFromDropEvent membaca berkas dari event', () => {
    const file = realFile('toko.png');

    expect(fileFromDropEvent({ dataTransfer: { files: listOf(file) } })).toBe(file);
    expect(fileFromInputEvent({ target: { files: listOf(file) } })).toBe(file);
    expect(fileFromDropEvent({})).toBeNull();
    expect(fileFromInputEvent({ target: {} })).toBeNull();
  });

  it('toImageFormData menaruh berkas di field `image` (multipart backend)', () => {
    const file = realFile('kaos.jpg');
    const formData = toImageFormData(file);

    const stored = formData.get('image') as File | null;
    expect(stored?.name).toBe('kaos.jpg');
    expect(stored?.size).toBe(file.size);
  });
});

/** Event tiruan: cukup bentuk yang dibaca komponen (tanpa DOM). */
interface StubEvent {
  preventDefault: ReturnType<typeof vi.fn>;
  stopPropagation: ReturnType<typeof vi.fn>;
  key?: string;
  dataTransfer?: { files: unknown };
}

function stubEvent(extra: Partial<StubEvent> = {}): StubEvent {
  return { preventDefault: vi.fn(), stopPropagation: vi.fn(), ...extra };
}

function box(overrides: Partial<ImageBoxProps> = {}) {
  return ImageBox({
    uploading: false,
    dragActive: false,
    disabled: false,
    size: 'sm',
    onPick: vi.fn(),
    onDrop: vi.fn(),
    onDragOver: vi.fn(),
    onDragLeave: vi.fn(),
    onDelete: vi.fn(),
    ...overrides,
  });
}

/** Kotak gambar (elemen `role="button"` pertama). */
function boxElement(tree: ReturnType<typeof box>) {
  const found = findElement(tree, (element) => element.props['data-image-upload'] !== undefined);
  expect(found).toBeDefined();

  return found!;
}

function deleteButton(tree: ReturnType<typeof box>) {
  return findElement(tree, (element) => element.props['aria-label'] === 'Hapus gambar');
}

describe('K5.3 — ImageBox (PURE, tanpa hook)', () => {
  it('tanpa gambar: placeholder ikon + atribut data-image-upload="empty"', () => {
    const tree = box({
      fallbackIcon: createElement('svg', { 'data-fallback': 'package' }),
    });
    const html = htmlOf(tree);

    expect(attrOf(tree, 'data-image-upload')).toBe('empty');
    expect(html).not.toContain('<img');
    expect(textOf(tree)).toContain('Klik / tarik gambar');
    expect(attrOf(tree, 'data-fallback')).toBe('package');
  });

  it('dengan gambar: <img object-cover> + tombol hapus muncul', () => {
    const tree = box({ url: 'http://localhost:8000/media/products/2026/10/kaos.png' });
    const html = htmlOf(tree);

    expect(attrOf(tree, 'data-image-upload')).toBe('filled');
    expect(html).toContain('src="http://localhost:8000/media/products/2026/10/kaos.png"');
    expect(html).toContain('object-cover');
    expect(deleteButton(tree)).toBeDefined();
  });

  it('tanpa gambar: tombol hapus TIDAK dirender', () => {
    expect(deleteButton(box())).toBeUndefined();
  });

  it('klik tombol hapus → onDelete dipanggil (event dihentikan)', () => {
    const onDelete = vi.fn();
    const tree = box({ url: 'http://localhost:8000/media/x.png', onDelete });
    const button = deleteButton(tree);
    const event = stubEvent();

    callProp(button!, 'onClick', event);

    expect(onDelete).toHaveBeenCalledTimes(1);
    expect(event.stopPropagation).toHaveBeenCalled();
  });

  it('klik kotak → onPick; tombol hapus TIDAK memicu onPick', () => {
    const onPick = vi.fn();
    const tree = box({ onPick });

    callProp(boxElement(tree), 'onClick');

    expect(onPick).toHaveBeenCalledTimes(1);
  });

  it('drop berkas → onDrop(event) diteruskan (keputusan ada di ImageUpload)', () => {
    const onDrop = vi.fn();
    const tree = box({ onDrop });
    const event = stubEvent({ dataTransfer: { files: listOf(realFile()) } });

    callProp(boxElement(tree), 'onDrop', event);

    expect(onDrop).toHaveBeenCalledWith(event);
  });

  it('dragActive: atribut drag + ring sorotan', () => {
    const tree = box({ dragActive: true });
    const html = htmlOf(tree);

    expect(attrOf(tree, 'data-image-upload-drag')).toBe('true');
    expect(html).toContain('ring-2');
    expect(textOf(tree)).toContain('Lepaskan berkas');
  });

  it('uploading: overlay spinner muncul (role="status")', () => {
    expect(htmlOf(box({ uploading: true }))).toContain('role="status"');
    expect(htmlOf(box())).not.toContain('role="status"');
  });

  it('disabled: aria-disabled + Enter tidak memanggil onPick', () => {
    const onPick = vi.fn();
    const tree = box({ disabled: true, onPick });
    const event = stubEvent({ key: 'Enter' });

    expect(attrOf(tree, 'aria-disabled')).toBe('true');
    expect(attrOf(tree, 'tabindex')).toBe('-1');

    callProp(boxElement(tree), 'onKeyDown', event);

    expect(onPick).not.toHaveBeenCalled();
    expect(event.preventDefault).not.toHaveBeenCalled();
  });

  it('errorMessage: pesan validasi tampil sebagai role="alert"', () => {
    const tree = box({ errorMessage: 'Format tidak didukung.' });

    const alert = findElement(tree, (element) => element.props['role'] === 'alert');

    expect(alert).toBeDefined();
    expect(textOf(tree)).toContain('Format tidak didukung.');
  });
});

describe('K5.3 — ImageUpload (render nyata via react-dom/server)', () => {
  it('tanpa gambar: kotak placeholder + input file (accept 3 format)', () => {
    const html = htmlOf(createElement(ImageUpload, { onUpload: vi.fn(), size: 'sm' }));

    expect(html).toContain('data-image-upload="empty"');
    expect(html).toContain('aria-label="Berkas gambar"');
    expect(html).toContain(IMAGE_ACCEPT);
    expect(html).toContain('Klik / tarik gambar');
  });

  it('dengan gambar: <img> + tombol hapus + fallbackIcon kustom', () => {
    const html = htmlOf(
      createElement(ImageUpload, {
        currentUrl: 'http://localhost:8000/media/partners/2026/10/toko.png',
        fallbackIcon: createElement('svg', { 'data-fallback': 'users' }),
        onUpload: vi.fn(),
        onDelete: vi.fn(),
        size: 'sm',
      }),
    );

    expect(html).toContain('src="http://localhost:8000/media/partners/2026/10/toko.png"');
    expect(html).toContain('Hapus gambar');
    expect(html).toContain('aria-label="Ganti gambar"');
  });

  it('uploading=true: spinner tampil + input file nonaktif', () => {
    const html = htmlOf(
      createElement(ImageUpload, { onUpload: vi.fn(), uploading: true, size: 'sm' }),
    );

    expect(html).toContain('role="status"');
    expect(html).toContain('disabled');
    expect(html).toContain('aria-disabled="true"');
  });
});

describe('K5.5 — ImageUpload me-resolve URL relatif backend', () => {
  it('currentUrl `/media/...` → src absolut origin backend (bukan origin :5173)', () => {
    vi.stubEnv('VITE_API_BASE_URL', 'http://localhost:8000/api/v1');

    const html = htmlOf(
      createElement(ImageUpload, {
        currentUrl: '/media/products/2026/10/kaos.jpg',
        onUpload: vi.fn(),
        size: 'sm',
      }),
    );

    expect(html).toContain('src="http://localhost:8000/media/products/2026/10/kaos.jpg"');
  });
});
