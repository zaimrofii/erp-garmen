import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

/**
 * FASE K5.3 — wiring kotak gambar (`ImageUpload`) di dua halaman detail master.
 *
 * Uji SUMBER (`readFileSync`) mengikuti gaya H1.1/H1.6 di file test halaman: tanpa
 * jsdom, cukup membuktikan halaman memakai adapter gambar, memakai `image_display_url`
 * dari baris API, dan menyegarkan query setelah aksi.
 */

const ROOT = path.resolve(import.meta.dirname, '../../..');

function read(relative: string): string {
  return readFileSync(path.join(ROOT, relative), 'utf8');
}

const PRODUCT_PAGE = read('src/pages/master/ProductDetailPage.tsx');
const PARTNER_PAGE = read('src/pages/master/PartnerDetailPage.tsx');

describe('K5.3 — kotak gambar di ProductDetailPage', () => {
  it('ImageUpload dipasang di header dengan fallback ikon Package (ukuran sm)', () => {
    expect(PRODUCT_PAGE).toContain('import { ImageUpload } from "@/components/molecules/ImageUpload"');
    expect(PRODUCT_PAGE).toContain('currentUrl={product.image_display_url}');
    expect(PRODUCT_PAGE).toMatch(
      /fallbackIcon=\{\s*<Package className="h-6 w-6" aria-hidden="true" \/>\s*\}/,
    );
    expect(PRODUCT_PAGE).toContain('size="sm"');
    expect(PRODUCT_PAGE).toContain('onUpload={handleUploadImage}');
    expect(PRODUCT_PAGE).toContain('onDelete={handleDeleteImage}');
    expect(PRODUCT_PAGE).toContain('uploading={imageBusy}');
  });

  it('unggah memakai uploadProductImage + invalidate & refetch query detail', () => {
    expect(PRODUCT_PAGE).toMatch(
      /import \{\s*deleteProductImage,\s*fetchProduct,\s*uploadProductImage,?\s*\} from "@\/api\/masterProducts"/,
    );
    expect(PRODUCT_PAGE).toContain('uploadProductImage(client, productId, file)');
    expect(PRODUCT_PAGE).toMatch(
      /queryClient\.invalidateQueries\(\{\s*queryKey: \["master-product", productId\],?\s*\}\)/,
    );
    expect(PRODUCT_PAGE).toContain('await refetch();');
  });

  it('hapus memakai deleteProductImage + toast sukses/gagal (validasi klien → toast error)', () => {
    expect(PRODUCT_PAGE).toContain('deleteProductImage(client, productId)');
    expect(PRODUCT_PAGE).toContain('title: "Gambar produk tersimpan"');
    expect(PRODUCT_PAGE).toContain('title: "Gambar produk dihapus"');
    expect(PRODUCT_PAGE).toMatch(
      /setToast\(\{\s*title: "Gambar ditolak",\s*description: message,\s*tone: "error",?\s*\}\)/,
    );
    expect(PRODUCT_PAGE).toContain('import { Toast, type ToastTone } from "@/components/atoms/Toast"');
  });
});

describe('K5.3 — kotak gambar di PartnerDetailPage', () => {
  it('ImageUpload dipasang di header dengan fallback ikon Users (ukuran sm)', () => {
    expect(PARTNER_PAGE).toContain('import { ImageUpload } from "@/components/molecules/ImageUpload"');
    expect(PARTNER_PAGE).toContain('currentUrl={partner.image_display_url}');
    expect(PARTNER_PAGE).toContain('fallbackIcon={<Users className="h-6 w-6" aria-hidden="true" />}');
    expect(PARTNER_PAGE).toContain('size="sm"');
    expect(PARTNER_PAGE).toContain('uploading={imageBusy}');
  });

  it('unggah/hapus memakai adapter partner + invalidate & refetch query detail', () => {
    expect(PARTNER_PAGE).toContain(
      'import { deletePartnerImage, fetchPartner, uploadPartnerImage } from "@/api/masterPartners"',
    );
    expect(PARTNER_PAGE).toContain('uploadPartnerImage(client, partnerId, file)');
    expect(PARTNER_PAGE).toContain('deletePartnerImage(client, partnerId)');
    expect(PARTNER_PAGE).toContain('queryClient.invalidateQueries({ queryKey: ["master-partner", partnerId] })');
    expect(PARTNER_PAGE).toContain('title: "Gambar partner dihapus"');
  });
});

describe('K5.3 — batas read-only halaman detail tetap dijaga', () => {
  it('tanpa useMutation & tanpa soft delete entitas dari halaman detail', () => {
    for (const [label, page, pattern] of [
      ['produk', PRODUCT_PAGE, /\bdeleteProduct\(/],
      ['partner', PARTNER_PAGE, /\bdeletePartner\(/],
    ] as const) {
      expect(page, label).not.toContain('useMutation');
      expect(page, label).not.toMatch(pattern);
    }
  });
});
