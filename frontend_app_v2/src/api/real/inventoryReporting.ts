// REAL - inventory reporting (F5.4.CLOSE / backend B30). GET `/inventory/reporting/`
// (+ `?location_code=WH/WIP`).
//
// Bentuk backend = agregat stok **per lokasi MES** (bukan daftar mutasi stok) —
// amplop khusus, bukan ListPage:
//
//   {"rows": [{"location_code", "location_name", "product_count", "total_qty",
//              "last_updated"}],
//    "total_locations": 4, "generated_at": "ISO-8601"}
//
// Fail-safe backend: env `ODOO_LOCATION_*` kosong → baris tetap ada dengan nilai 0
// dan `last_updated=null`; halaman harus tetap menampilkan baris tersebut.
import type { ApiClient } from '@/integrations/api-client';
import { buildQueryPath, getParsed, isRecord, readNullableStr, readNum, readStr } from './_shape';

export const INVENTORY_REPORTING_PATH = '/inventory/reporting/';

export interface LocationStockRow {
  /** `WH/WIP` | `Virtual/Production` | `WH/FG` | `Virtual/Scrap`. */
  location_code: string;
  location_name: string;
  /** Jumlah produk distinct dengan bundle/order line termapping. */
  product_count: number;
  total_qty: number;
  last_updated: string | null;
}

export interface LocationStockReport {
  rows: LocationStockRow[];
  total_locations: number;
  /** Waktu server membentuk laporan (ISO-8601). */
  generated_at: string;
}

/** PURE — satu baris backend → `LocationStockRow`. */
export function readLocationStockRow(raw: unknown): LocationStockRow | null {
  if (!isRecord(raw)) return null;

  return {
    location_code: readStr(raw['location_code']),
    location_name: readStr(raw['location_name']),
    product_count: readNum(raw['product_count']),
    total_qty: readNum(raw['total_qty']),
    last_updated: readNullableStr(raw['last_updated']),
  };
}

/** PURE — respons laporan → `LocationStockReport`. */
export function readLocationStockReport(raw: unknown): LocationStockReport | null {
  if (!isRecord(raw)) return null;
  const rows = raw['rows'];
  if (!Array.isArray(rows)) return null;

  const parsed: LocationStockRow[] = [];
  for (const row of rows) {
    const item = readLocationStockRow(row);
    if (item !== null) parsed.push(item);
  }

  return {
    rows: parsed,
    total_locations: readNum(raw['total_locations']),
    generated_at: readStr(raw['generated_at']),
  };
}

/** PURE — path + `?location_code=`. */
export function buildInventoryReportingPath(
  params: { locationCode?: string | null } = {},
): string {
  return buildQueryPath(INVENTORY_REPORTING_PATH, { location_code: params.locationCode });
}

/** Laporan stok per lokasi. Gagal HTTP → melempar. */
export async function fetchLocationStock(
  client: ApiClient,
  params: { locationCode?: string | null } = {},
): Promise<LocationStockReport> {
  return getParsed(
    client,
    buildInventoryReportingPath(params),
    readLocationStockReport,
    'laporan stok per lokasi',
  );
}
