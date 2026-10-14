/**
 * printer-config.ts — kontrak Printer Config (`/api/v1/settings/printer/`, H5.7).
 *
 * **Singleton** (1 baris) + **Opsi B** (pola H5.6/H5.8): DB menyimpan **profil printer**,
 * tetapi **konsumen tetap membaca `.env`** (`integrations/printing.backends.get_backend()`
 * dipakai `integrations/printing/api.py`: bundle tag + kupon) — perubahan baru aktif
 * setelah disalin ke `.env` dan restart `django`/`celery_worker`/`celery_beat`
 * (`restart_command`).
 *
 * Field = PERSIS `django_app/master/printer_config_services.py::config_row` (6 field):
 *   * ``printer_backend`` — ``'mock'`` | ``'usb'`` | ``'network'`` (env `PRINTER_BACKEND`);
 *   * ``printer_usb_vendor_id`` / ``printer_usb_product_id`` — env `PRINTER_USB_*`
 *     (wajib bila backend ``usb``);
 *   * ``printer_network_host`` / ``printer_network_port`` — env `PRINTER_NETWORK_*`
 *     (wajib bila backend ``network``; port 1..65535);
 *   * ``printer_mock_dir`` — env `PRINTER_MOCK_DIR` (opsional; kosong = default server).
 *
 * ⚠️ **Tanpa mask**: host/port/USB id/folder printer **bukan** kredensial (beda dari
 * `odoo_api_key` H5.6 & `wa_api_key` H5.8) — nilai dikirim apa adanya oleh backend.
 *
 * Respons GET/PUT juga membawa `effective`, `diverges`, `needs_restart`, `restart_command`.
 */

/** Backend printer yang dikenal backend (`PrinterConfig.Backend`). */
export const PRINTER_BACKENDS = ['mock', 'usb', 'network'] as const;
export type PrinterBackend = (typeof PRINTER_BACKENDS)[number];

/** Rentang port TCP yang sah (selaras service backend). */
export const PRINTER_PORT_MIN = 1;
export const PRINTER_PORT_MAX = 65535;

/** Batas panjang teks (selaras kolom model backend). */
export const PRINTER_MAX_VENDOR = 32;
export const PRINTER_MAX_PRODUCT = 32;
export const PRINTER_MAX_HOST = 200;
export const PRINTER_MAX_DIR = 200;

export interface PrinterConfigRow {
  id: number;
  printer_backend: string;
  printer_usb_vendor_id: string;
  printer_usb_product_id: string;
  printer_network_host: string;
  /** ``null`` = belum diisi (kolom ``PositiveIntegerField`` nullable). */
  printer_network_port: number | null;
  printer_mock_dir: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

/** Satu field yang beda antara profil DB dan `.env` (tanpa mask — bukan rahasia). */
export interface PrinterConfigDivergence {
  db: string | number | null;
  env: string | number | null;
}

/** Nilai profil tanpa metadata (bentuk yang sama untuk ``config`` & ``effective``). */
export type PrinterConfigValues = Omit<
  PrinterConfigRow,
  'id' | 'is_active' | 'created_at' | 'updated_at'
>;

/** Respons `GET`/`PUT /settings/printer/`. */
export interface PrinterConfigEnvelope {
  config: PrinterConfigRow | null;
  /** Profil yang **aktif** sekarang (dari `.env`/settings) — read-only untuk UI. */
  effective: PrinterConfigValues;
  /** Field yang **beda** DB vs `.env` — kosong = sudah selaras. */
  diverges: Record<string, PrinterConfigDivergence>;
  /** ``bool(diverges)`` — True = perlu salin ke `.env` + restart worker. */
  needs_restart: boolean;
  /** Perintah aktivasi (mis. `docker compose restart django celery_worker celery_beat`). */
  restart_command: string;
}

/**
 * Body `PUT /settings/printer/` — hanya field yang dikirim yang diubah
 * (create-on-first-PUT). ``printer_network_port`` boleh ``null``/kosong = hapus.
 */
export interface PrinterConfigInput {
  printer_backend?: string;
  printer_usb_vendor_id?: string;
  printer_usb_product_id?: string;
  printer_network_host?: string;
  printer_network_port?: number | null;
  printer_mock_dir?: string;
  active?: boolean;
}

/** Respons `POST /settings/printer/test-connection/` (read-only, tidak mencetak). */
export interface PrinterTestConnectionResult {
  ok: boolean;
  backend: string;
  message: string;
}
