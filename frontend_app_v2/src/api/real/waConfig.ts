// REAL - WA Gateway Config (H5.8). Endpoint: `/api/v1/settings/wa/` (SINGLETON)
//   GET  `/settings/wa/` → {config, effective, diverges, needs_restart, restart_command}
//   PUT  `/settings/wa/` → amplop yang sama (create-on-first-PUT; ADMIN/OWNER)
//   POST `/settings/wa/test-connection/` → {ok, backend, url, mock, message}
//
// Pemetaan UI ↔ backend (tidak ada shape yang dikarang):
//   * baris `{id, wa_backend, wa_api_url, wa_api_key, is_active, created_at, updated_at}`;
//   * `wa_api_key` **selalu** `***` bila terisi (rahasia tidak pernah dikirim apa adanya);
//   * `effective` = nilai `.env` yang aktif; `diverges` = `{field: {db, env}}` (masked);
//   * `needs_restart` = bool(diverges) — aktivasi butuh salin ke `.env` + restart worker.
//
// Catatan: `ApiClient` hanya punya `get`/`post` — PUT lewat `client.request()`.
import type { ApiClient } from '@/integrations/api-client';
import type {
  WAConfigDivergence,
  WAConfigEnvelope,
  WAConfigInput,
  WAConfigRow,
  WAConfigValues,
  WATestConnectionResult,
} from '@/types/wa-config';
import { unwrap } from '../client';
import { isRecord, readBool, readStr } from './_shape';

/** Path relatif terhadap `VITE_API_BASE_URL` (`…/api/v1`). */
export const SETTINGS_WA_PATH = '/settings/wa/';

/** Path uji gateway WA (POST, read-only — tidak mengirim pesan). */
export const WA_TEST_CONNECTION_PATH = `${SETTINGS_WA_PATH}test-connection/`;

/** PURE — nilai satu field `diverges` (`db`/`env`): string | angka | null. */
export function readDivergenceValue(value: unknown): string | number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string') return value;

  return null;
}

/** PURE — satu entri `diverges` → `{db, env}`; `null` kalau bukan objek. */
export function readDivergence(raw: unknown): WAConfigDivergence | null {
  if (!isRecord(raw)) return null;

  return {
    db: readDivergenceValue(raw['db']),
    env: readDivergenceValue(raw['env']),
  };
}

/** PURE — 3 field nilai gateway (tanpa `id`/status/timestamp). */
export function readWAConfigValues(raw: unknown): WAConfigValues | null {
  if (!isRecord(raw)) return null;

  return {
    wa_backend: readStr(raw['wa_backend']),
    wa_api_url: readStr(raw['wa_api_url']),
    wa_api_key: readStr(raw['wa_api_key']),
  };
}

/** PURE — satu baris profil (`null` kalau tanpa `id` angka). */
export function readWAConfigRow(raw: unknown): WAConfigRow | null {
  if (!isRecord(raw)) return null;

  const id = raw['id'];
  if (typeof id !== 'number' || !Number.isFinite(id)) return null;

  const values = readWAConfigValues(raw);
  if (values === null) return null;

  return {
    id,
    ...values,
    is_active: readBool(raw['is_active']),
    created_at: readStr(raw['created_at']),
    updated_at: readStr(raw['updated_at']),
  };
}

/**
 * PURE — amplop respons → `WAConfigEnvelope | null`.
 *
 * `config` boleh `null` (profil belum diisi), tetapi `effective` **wajib** objek —
 * kalau tidak, respons dianggap tidak dikenali.
 */
export function readWAConfigEnvelope(raw: unknown): WAConfigEnvelope | null {
  if (!isRecord(raw)) return null;

  const effective = readWAConfigValues(raw['effective']);
  if (effective === null) return null;

  const diverges: Record<string, WAConfigDivergence> = {};
  const rawDiverges = raw['diverges'];
  if (isRecord(rawDiverges)) {
    for (const [field, value] of Object.entries(rawDiverges)) {
      const parsed = readDivergence(value);
      if (parsed !== null) diverges[field] = parsed;
    }
  }

  return {
    config: readWAConfigRow(raw['config']),
    effective,
    diverges,
    needs_restart: readBool(raw['needs_restart']),
    restart_command: readStr(raw['restart_command']),
  };
}

/** PURE — body `PUT` (hanya field yang ada di input). */
export function toWAConfigBody(input: WAConfigInput): Record<string, unknown> {
  const keys: (keyof WAConfigInput)[] = ['wa_backend', 'wa_api_url', 'wa_api_key', 'active'];
  const body: Record<string, unknown> = {};

  for (const key of keys) {
    const value = input[key];
    if (value === undefined) continue;
    // `wa_api_url` di-trim; `wa_api_key` SENGAJA apa adanya (nilai rahasia / `***`
    // = jangan ubah).
    body[key] = key === 'wa_api_url' && typeof value === 'string' ? value.trim() : value;
  }

  return body;
}

/** PURE — respons `test-connection`; `null` kalau bentuk tidak dikenali. */
export function readTestConnection(raw: unknown): WATestConnectionResult | null {
  if (!isRecord(raw)) return null;
  if (typeof raw['ok'] !== 'boolean') return null;

  return {
    ok: raw['ok'],
    backend: readStr(raw['backend']),
    url: raw['url'] === null || raw['url'] === undefined ? null : readStr(raw['url']),
    mock: raw['mock'] === true,
    message: readStr(raw['message']),
  };
}

/** Profil + effective + divergences (`GET`). Gagal HTTP → melempar. */
export async function fetchWAConfig(client: ApiClient): Promise<WAConfigEnvelope> {
  const envelope = readWAConfigEnvelope(unwrap(await client.get<unknown>(SETTINGS_WA_PATH)));
  if (envelope === null) {
    throw new Error('Bentuk respons konfigurasi WA tidak dikenali.');
  }

  return envelope;
}

/** Simpan profil gateway (PUT, ADMIN/OWNER; create-on-first-PUT) → amplop terbaru. */
export async function updateWAConfig(
  client: ApiClient,
  input: WAConfigInput,
): Promise<WAConfigEnvelope> {
  const envelope = readWAConfigEnvelope(
    unwrap(
      await client.request<unknown>(SETTINGS_WA_PATH, {
        method: 'PUT',
        body: toWAConfigBody(input),
      }),
    ),
  );
  if (envelope === null) {
    throw new Error('Bentuk respons simpan konfigurasi WA tidak dikenali.');
  }

  return envelope;
}

/** Uji gateway WA (POST, read-only, nilai `.env`) → hasil uji. */
export async function testWAConnection(client: ApiClient): Promise<WATestConnectionResult> {
  const result = readTestConnection(
    unwrap(await client.post<unknown>(WA_TEST_CONNECTION_PATH, {})),
  );
  if (result === null) {
    throw new Error('Bentuk respons uji gateway WA tidak dikenali.');
  }

  return result;
}

