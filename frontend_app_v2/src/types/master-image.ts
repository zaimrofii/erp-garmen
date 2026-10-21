/**
 * master-image.ts — bentuk data endpoint gambar master (K5.2 backend, K5.3 frontend).
 *
 * Endpoint: `POST|DELETE /api/v1/master/products/<id>/image/` dan
 * `/api/v1/master/partners/<id>/image/` — multipart field `image`, guard ADMIN/OWNER.
 *
 * Response sukses (`master/image_services.py::image_payload`):
 *   * `image_file_url`      = URL berkas asli (`null` kalau gambar dihapus);
 *   * `image_display_url`   = URL tampilan (unggahan menang atas `image_url` lama);
 *   * `image_thumbnail_url` = URL thumbnail 256px (`null` kalau belum dibuat);
 *   * `warning`             = ada bila thumbnail gagal dibuat (unggahan tetap sukses);
 *   * `deleted_files`       = daftar berkas yang terhapus (khusus DELETE).
 */
export interface MasterImagePayload {
  id: number;
  image_file_url: string | null;
  image_display_url: string | null;
  image_thumbnail_url: string | null;
  message: string;
  warning?: string;
  deleted_files?: string[];
}

/**
 * Tiga URL gambar yang menempel di baris produk/partner.
 *
 * Ditandai opsional supaya fixture lama (test/data lama) tetap sah: backend K5.2
 * SELALU mengirim ketiganya, jadi `undefined` praktis sama dengan `null`.
 */
export interface MasterImageFields {
  image_file_url?: string | null;
  image_display_url?: string | null;
  image_thumbnail_url?: string | null;
}
