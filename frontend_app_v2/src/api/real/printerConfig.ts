// REAL - Printer Config (H5.7). Endpoint: `/api/v1/settings/printer/` (SINGLETON)
//   GET  `/settings/printer/` → {config, effective, diverges, needs_restart, restart_command}
//   PUT  `/settings/printer/` → amplop yang sama (create-on-first-PUT; ADMIN/OWNER)
//   POST `/settings/printer/test-connection/` → {ok, backend, message}
//
// Pemetaan UI ↔ backend (tidak ada shape yang dikarang):
//   * baris `{id, printer_backend, printer_usb_vendor_id, printer_usb_product_id,
//     printer_network_host, printer_network_port, printer_mock_dir, is_active,
//     created_at, updated_at}` — **tanpa mask** (bukan data rahasia);
//   * `effective` = nilai `.env` yang aktif; `diverges` = `{field: {db, env}}`;
//   * `needs_restart` = bool(diverges) — aktivasi butuh salin ke `.env` + restart worker.
//
// Catatan: `ApiClient` hanya punya `get`/`post` — PUT lewat `client.request()`.
import type { ApiClient } from '@/integrations/api-client';
import type {
  PrinterConfigDivergence,
  PrinterConfigEnvelope,
  PrinterConfigInput,
  PrinterConfigRow,
  PrinterConfigValues,
  PrinterTestConnectionResult,
} from '@/types/printer-config';
import { unwrap } from '../client';
import { isRecord, readBool, readNullableNum, readStr } from './_shape';

/** Path relatif terhadap `VITE_API_BASE_URL` (`…/api/v1`). */
export const SETTINGS_PRINTER_PATH = '/settings/printer/';

/** Path uji printer (POST, read-only — tidak pernah mencetak). */
export const PRINTER_TEST_CONNECTION_PATH = `${SETTINGS_PRINTER_PATH}test-connection/`;

/** PURE — nilai satu field `diverges` (`db`/`env`): string | angka | null. */
export function readDivergenceValue(value: unknown): string | number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string') return value;

  return null;
}

/** PURE — satu entri `diverges` → `{db, env}`; `null` kalau bukan objek. */
export function readDivergence(raw: unknown): PrinterConfigDivergence | null {
  if (!isRecord(raw)) return null;

  return {
    db: readDivergenceValue(raw['db']),
    env: readDivergenceValue(raw['env']),
  };
}

/** PURE — 6 field nilai printer (tanpa `id`/status/timestamp). */
export function readPrinterConfigValues(raw: unknown): PrinterConfigValues | null {
  if (!isRecord(raw)) return null;

  return {
    printer_backend: readStr(raw['printer_backend']),
    printer_usb_vendor_id: readStr(raw['printer_usb_vendor_id']),
    printer_usb_product_id: readStr(raw['printer_usb_product_id']),
    printer_network_host: readStr(raw['printer_network_host']),
    printer_network_port: readNullableNum(raw['printer_network_port']),
    printer_mock_dir: readStr(raw['printer_mock_dir']),
  };
}

/** PURE — satu baris profil (`null` kalau tanpa `id` angka). */
export function readPrinterConfigRow(raw: unknown): PrinterConfigRow | null {
  if (!isRecord(raw)) return null;

  const id = raw['id'];
  if (typeof id !== 'number' || !Number.isFinite(id)) return null;

  const values = readPrinterConfigValues(raw);
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
 * PURE — amplop respons → `PrinterConfigEnvelope | null`.
 *
 * `config` boleh `null` (profil belum diisi), tetapi `effective` **wajib** objek —
 * kalau tidak, respons dianggap tidak dikenali.
 */
export function readPrinterConfigEnvelope(raw: unknown): PrinterConfigEnvelope | null {
  if (!isRecord(raw)) return null;

  const effective = readPrinterConfigValues(raw['effective']);
  if (effective === null) return null;

  const diverges: Record<string, PrinterConfigDivergence> = {};
  const rawDiverges = raw['diverges'];
  if (isRecord(rawDiverges)) {
    for (const [field, value] of Object.entries(rawDiverges)) {
      const parsed = readDivergence(value);
      if (parsed !== null) diverges[field] = parsed;
    }
  }

  return {
    config: readPrinterConfigRow(raw['config']),
    effective,
    diverges,
    needs_restart: readBool(raw['needs_restart']),
    restart_command: readStr(raw['restart_command']),
  };
}

/** PURE — body `PUT` (hanya field yang ada di input). */
export function toPrinterConfigBody(input: PrinterConfigInput): Record<string, unknown> {
  const keys: (keyof PrinterConfigInput)[] = [
    'printer_backend',
    'printer_usb_vendor_id',
    'printer_usb_product_id',
    'printer_network_host',
    'printer_network_port',
    'printer_mock_dir',
    'active',
  ];
  const body: Record<string, unknown> = {};

  for (const key of keys) {
    const value = input[key];
    if (value === undefined) continue;
    // teks dikirim ter-trim (tidak ada rahasia di H5.7, jadi aman di-trim)
    body[key] = typeof value === 'string' ? value.trim() : value;
  }

  return body;
}

/** PURE — respons `test-connection`; `null` kalau bentuk tidak dikenali. */
export function readTestConnection(raw: unknown): PrinterTestConnectionResult | null {
  if (!isRecord(raw)) return null;
  if (typeof raw['ok'] !== 'boolean') return null;

  return {
    ok: raw['ok'],
    backend: readStr(raw['backend']),
    message: readStr(raw['message']),
  };
}

/** Profil + effective + divergences (`GET`). Gagal HTTP → melempar. */
export async function fetchPrinterConfig(client: ApiClient): Promise<PrinterConfigEnvelope> {
  const envelope = readPrinterConfigEnvelope(
    unwrap(await client.get<unknown>(SETTINGS_PRINTER_PATH)),
  );
  if (envelope === null) {
    throw new Error('Bentuk respons konfigurasi printer tidak dikenali.');
  }

  return envelope;
}

/** Simpan profil printer (PUT, ADMIN/OWNER; create-on-first-PUT) → amplop terbaru. */
export async function updatePrinterConfig(
  client: ApiClient,
  input: PrinterConfigInput,
): Promise<PrinterConfigEnvelope> {
  const envelope = readPrinterConfigEnvelope(
    unwrap(
      await client.request<unknown>(SETTINGS_PRINTER_PATH, {
        method: 'PUT',
        body: toPrinterConfigBody(input),
      }),
    ),
  );
  if (envelope === null) {
    throw new Error('Bentuk respons simpan konfigurasi printer tidak dikenali.');
  }

  return envelope;
}

/** Uji printer (POST, read-only, nilai `.env`; TIDAK mencetak) → hasil uji. */
export async function testPrinterConnection(
  client: ApiClient,
): Promise<PrinterTestConnectionResult> {
  const result = readTestConnection(
    unwrap(await client.post<unknown>(PRINTER_TEST_CONNECTION_PATH, {})),
  );
  if (result === null) {
    throw new Error('Bentuk respons uji printer tidak dikenali.');
  }

  return result;
}

