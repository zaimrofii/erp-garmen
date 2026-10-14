// ADAPTER - satu-satunya pintu data Printer Config (H5.7, TANPA logic domain).
//
// H5.7: endpoint `/api/v1/settings/printer/` SUDAH ADA di backend →
// MODE.printerConfig = 'real' (`_adapter.ts`), jadi tidak ada implementasi dummy.
//
// **SINGLETON + Opsi B**: DB menyimpan *profil printer*; konsumen
// (`integrations/printing.backends.get_backend`) tetap membaca `.env`. GET mengembalikan
// `config` + `effective` + `diverges` + `needs_restart` + `restart_command`.
import { pickAdapter } from './_adapter';
import * as real from './real/printerConfig';

/** Profil + effective + divergences (`GET /settings/printer/`) — REAL (H5.7). */
export const fetchPrinterConfig = pickAdapter(
  'printerConfig',
  real.fetchPrinterConfig,
  real.fetchPrinterConfig,
);

/** Simpan profil printer (`PUT /settings/printer/`) — REAL (H5.7; izin admin/owner). */
export const updatePrinterConfig = pickAdapter(
  'printerConfig',
  real.updatePrinterConfig,
  real.updatePrinterConfig,
);

/** Uji printer (`POST …/test-connection/`, read-only, tidak mencetak) — REAL (H5.7). */
export const testPrinterConnection = pickAdapter(
  'printerConfig',
  real.testPrinterConnection,
  real.testPrinterConnection,
);

export {
  PRINTER_TEST_CONNECTION_PATH,
  readDivergence,
  readDivergenceValue,
  readPrinterConfigEnvelope,
  readPrinterConfigRow,
  readPrinterConfigValues,
  readTestConnection,
  SETTINGS_PRINTER_PATH,
  toPrinterConfigBody,
} from './real/printerConfig';
export type {
  PrinterBackend,
  PrinterConfigDivergence,
  PrinterConfigEnvelope,
  PrinterConfigInput,
  PrinterConfigRow,
  PrinterConfigValues,
  PrinterTestConnectionResult,
} from '@/types/printer-config';
export {
  PRINTER_BACKENDS,
  PRINTER_MAX_DIR,
  PRINTER_MAX_HOST,
  PRINTER_MAX_PRODUCT,
  PRINTER_MAX_VENDOR,
  PRINTER_PORT_MAX,
  PRINTER_PORT_MIN,
} from '@/types/printer-config';
