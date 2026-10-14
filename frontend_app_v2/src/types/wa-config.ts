/**
 * wa-config.ts — kontrak WA Gateway Config (`/api/v1/settings/wa/`, H5.8).
 *
 * **Singleton** (1 baris) + **Opsi B** (keputusan STEP 0, pola H5.6): DB menyimpan
 * **profil gateway**, tetapi **konsumen tetap membaca `.env`**
 * (`integrations/wa_bot/services.get_wa_gateway` dipakai `POST /api/v1/wa/send/`,
 * `tasks_reconciliation.py`, dan `ai/hitl_views.py`) — perubahan baru aktif setelah
 * disalin ke `.env` dan restart `django`/`celery_worker`/`celery_beat`
 * (`restart_command`).
 *
 * Field = PERSIS `django_app/master/wa_config_services.py::config_row` (3 field env):
 *   * ``wa_backend`` — ``'mock'`` | ``'real'`` | ``'api'`` (env `WA_BACKEND`);
 *   * ``wa_api_url`` — base URL penyedia (env `WA_API_URL`);
 *   * ``wa_api_key`` — **selalu ``***`` di response** (rahasia); kirim ``***`` = jangan ubah.
 *
 * Respons GET/PUT juga membawa:
 *   * ``effective`` — nilai `.env` yang **benar-benar aktif** sekarang (rahasia di-mask);
 *   * ``diverges`` — ``{field: {db, env}}`` untuk field yang beda (rahasia di-mask);
 *   * ``needs_restart`` — ``bool(diverges)``;
 *   * ``restart_command`` — perintah aktivasi yang ditampilkan UI.
 */

/** Mask rahasia yang dipakai backend (``wa_api_key``). */
export const SENSITIVE_MASK = '***';

export interface WAConfigRow {
  id: number;
  wa_backend: string;
  wa_api_url: string;
  /** **Selalu** ``***`` bila terisi di DB (rahasia tidak pernah dikirim apa adanya). */
  wa_api_key: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

/** Satu field yang beda antara profil DB dan `.env` (nilai rahasia sudah di-mask). */
export interface WAConfigDivergence {
  db: string | number | null;
  env: string | number | null;
}

/** Nilai profil tanpa metadata (bentuk yang sama untuk ``config`` & ``effective``). */
export type WAConfigValues = Omit<WAConfigRow, 'id' | 'is_active' | 'created_at' | 'updated_at'>;

/** Respons `GET`/`PUT /settings/wa/`. */
export interface WAConfigEnvelope {
  config: WAConfigRow | null;
  /** Gateway yang **aktif** sekarang (dari `.env`/settings) — read-only untuk UI. */
  effective: WAConfigValues;
  /** Field yang **beda** DB vs `.env` (rahasia di-mask) — kosong = sudah selaras. */
  diverges: Record<string, WAConfigDivergence>;
  /** ``bool(diverges)`` — True = perlu salin ke `.env` + restart worker. */
  needs_restart: boolean;
  /** Perintah aktivasi (mis. `docker compose restart django celery_worker celery_beat`). */
  restart_command: string;
}

/**
 * Body `PUT /settings/wa/` — hanya field yang dikirim yang diubah
 * (create-on-first-PUT). ``wa_api_key='***'`` = **jangan ubah**; ``''`` = hapus.
 */
export interface WAConfigInput {
  wa_backend?: string;
  wa_api_url?: string;
  wa_api_key?: string;
  active?: boolean;
}

/** Respons `POST /settings/wa/test-connection/` (read-only, tanpa mengirim pesan). */
export interface WATestConnectionResult {
  ok: boolean;
  backend: string;
  url: string | null;
  /** ``true`` = gateway mock (tidak menyentuh jaringan). */
  mock: boolean;
  message: string;
}
