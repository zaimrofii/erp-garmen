/**
 * integration-config.ts — kontrak Integration Config (`/api/v1/settings/integration/`, H5.6).
 *
 * **Singleton** (1 baris) + **Opsi B** (keputusan STEP 0): DB menyimpan **profil** config,
 * tetapi **konsumen tetap membaca `.env`** — perubahan baru aktif setelah disalin ke `.env`
 * dan restart `django`/`celery_worker`/`celery_beat` (`restart_command`).
 *
 * Field = PERSIS `django_app/master/integration_config_services.py::config_row` (16 field):
 *   * ``erp_adapter`` — ``'odoo'`` | ``'null'`` (sama dengan env `ERP_ADAPTER`);
 *   * ``odoo_url``/``odoo_db``/``odoo_user`` — kredensial (env `ODOO_URL`/`ODOO_DB`/`ODOO_USER`);
 *   * ``odoo_api_key`` — **selalu ``***`` di response** (rahasia); kirim ``***`` = jangan ubah;
 *   * ``odoo_timeout`` + 7 id Odoo + 3 field rekonsiliasi (lihat `ENV` di bawah).
 *
 * Respons GET/PUT juga membawa:
 *   * ``effective`` — nilai `.env` yang **benar-benar aktif** sekarang (rahasia di-mask);
 *   * ``diverges`` — ``{field: {db, env}}`` untuk field yang beda (rahasia di-mask);
 *   * ``needs_restart`` — ``bool(diverges)``;
 *   * ``restart_command`` — perintah aktivasi yang ditampilkan UI.
 */

/** Mask rahasia yang dipakai backend (``odoo_api_key``). */
export const SENSITIVE_MASK = '***';

export interface IntegrationConfigRow {
  id: number;
  erp_adapter: string;
  odoo_url: string;
  odoo_db: string;
  odoo_user: string;
  /** **Selalu** ``***`` bila terisi di DB (rahasia tidak pernah dikirim apa adanya). */
  odoo_api_key: string;
  odoo_timeout: number;
  odoo_location_wip_id: number | null;
  odoo_location_production_id: number | null;
  odoo_location_fg_id: number | null;
  odoo_location_scrap_id: number | null;
  odoo_uom_id: number | null;
  odoo_picking_type_internal_id: number | null;
  odoo_payment_journal_id: number | null;
  reconciliation_tolerance_units: number;
  reconciliation_tolerance_pct: number;
  reconciliation_alert_wa_to: string[];
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

/** Satu field yang beda antara profil DB dan `.env` (nilai rahasia sudah di-mask). */
export interface IntegrationConfigDivergence {
  db: string | number | number[] | string[] | null;
  env: string | number | number[] | string[] | null;
}

/** Nilai profil tanpa metadata (bentuk yang sama untuk ``config`` & ``effective``). */
export type IntegrationConfigValues = Omit<
  IntegrationConfigRow,
  'id' | 'is_active' | 'created_at' | 'updated_at'
>;

/** Respons `GET`/`PUT /settings/integration/`. */
export interface IntegrationConfigEnvelope {
  config: IntegrationConfigRow | null;
  /** Config yang **aktif** sekarang (dari `.env`/settings) — read-only untuk UI. */
  effective: IntegrationConfigValues;
  /** Field yang **beda** DB vs `.env` (rahasia di-mask) — kosong = sudah selaras. */
  diverges: Record<string, IntegrationConfigDivergence>;
  /** ``bool(diverges)`` — True = perlu salin ke `.env` + restart worker. */
  needs_restart: boolean;
  /** Perintah aktivasi (mis. `docker compose restart django celery_worker celery_beat`). */
  restart_command: string;
}

/**
 * Body `PUT /settings/integration/` — hanya field yang dikirim yang diubah
 * (create-on-first-PUT). ``odoo_api_key='***'`` = **jangan ubah**; ``''`` = hapus.
 */
export interface IntegrationConfigInput {
  erp_adapter?: string;
  odoo_url?: string;
  odoo_db?: string;
  odoo_user?: string;
  odoo_api_key?: string;
  odoo_timeout?: number;
  odoo_location_wip_id?: number | null;
  odoo_location_production_id?: number | null;
  odoo_location_fg_id?: number | null;
  odoo_location_scrap_id?: number | null;
  odoo_uom_id?: number | null;
  odoo_picking_type_internal_id?: number | null;
  odoo_payment_journal_id?: number | null;
  reconciliation_tolerance_units?: number;
  reconciliation_tolerance_pct?: number;
  reconciliation_alert_wa_to?: string[];
  active?: boolean;
}

/** Respons `POST /settings/integration/test-connection/` (read-only, tanpa efek samping). */
export interface TestConnectionResult {
  ok: boolean;
  adapter: string;
  url: string | null;
  server_version: string | null;
  message: string;
}
