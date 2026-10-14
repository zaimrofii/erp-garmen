/**
 * integration-config.ts — logic PURE halaman Integration Config (H5.6).
 *
 * Dipisah dari halaman supaya bisa diuji TANPA DOM (jsdom tidak jalan di bun —
 * `.clinerules` §ENVIRONMENT): validasi form (16 field), konversi form ↔ payload PUT,
 * dan helper tampilan untuk bagian **Status** (effective/diverges).
 *
 * Cermin `master/integration_config_services.py`: guard ``erp_adapter='odoo'`` ⇒
 * ``odoo_url``+``odoo_db``+``odoo_user`` wajib; ``odoo_api_key='***'`` = jangan ubah
 * (rahasia selalu di-mask backend); URL menerima hostname internal **tanpa TLD**
 * (``http://odoo:8069``) — `URLValidator` Django menolaknya, jadi aturan di sini sama
 * dengan ``_is_http_url`` backend.
 */
import type { SelectOption } from '@/components/atoms/Select';
import type {
  IntegrationConfigInput,
  IntegrationConfigRow,
  IntegrationConfigValues,
} from '@/types/integration-config';
import { SENSITIVE_MASK } from '@/types/integration-config';

/** Mask rahasia (sama dengan backend); nilai ini **tidak** mengubah API key. */
export const INTEGRATION_MASK = SENSITIVE_MASK;

/** Batas & opsi (selaras service backend). */
export const ADAPTER_VALUES = ['odoo', 'null'];
export const MIN_TIMEOUT = 1;
export const MAX_TIMEOUT = 600;
export const MAX_TOLERANCE_PCT = 1;
export const MAX_WA_LENGTH = 32;

/** Opsi dropdown adapter ERP. */
export const ADAPTER_OPTIONS: SelectOption[] = [
  { value: 'odoo', label: 'Odoo (JSON-RPC)' },
  { value: 'null', label: 'Null (tanpa ERP)' },
];

/** Label ramah per field (dipakai form + bagian Status/diverges). */
export const CONFIG_FIELD_LABELS: Record<string, string> = {
  erp_adapter: 'Adapter ERP',
  odoo_url: 'URL Odoo',
  odoo_db: 'Database Odoo',
  odoo_user: 'User Odoo',
  odoo_api_key: 'API key Odoo',
  odoo_timeout: 'Timeout Odoo (detik)',
  odoo_location_wip_id: 'Lokasi WIP',
  odoo_location_production_id: 'Lokasi Produksi',
  odoo_location_fg_id: 'Lokasi FG',
  odoo_location_scrap_id: 'Lokasi Scrap',
  odoo_uom_id: 'UoM default',
  odoo_picking_type_internal_id: 'Picking type internal',
  odoo_payment_journal_id: 'Journal pembayaran',
  reconciliation_tolerance_units: 'Toleransi unit',
  reconciliation_tolerance_pct: 'Toleransi rasio',
  reconciliation_alert_wa_to: 'Penerima alert WA',
};

/** Nilai form (semua input teks = string; `active` = flag). */
export interface IntegrationConfigFormValues {
  erp_adapter: string;
  odoo_url: string;
  odoo_db: string;
  odoo_user: string;
  odoo_api_key: string;
  odoo_timeout: string;
  odoo_location_wip_id: string;
  odoo_location_production_id: string;
  odoo_location_fg_id: string;
  odoo_location_scrap_id: string;
  odoo_uom_id: string;
  odoo_picking_type_internal_id: string;
  odoo_payment_journal_id: string;
  reconciliation_tolerance_units: string;
  reconciliation_tolerance_pct: string;
  reconciliation_alert_wa_to: string;
  active: boolean;
}

/** Pesan error per field (kosong = valid). */
export type IntegrationConfigFormErrors = Partial<
  Record<keyof IntegrationConfigFormValues, string>
>;

/** Nilai awal form (profil belum pernah diisi). */
export const EMPTY_INTEGRATION_FORM: IntegrationConfigFormValues = {
  erp_adapter: 'odoo',
  odoo_url: '',
  odoo_db: '',
  odoo_user: '',
  odoo_api_key: '',
  odoo_timeout: '30',
  odoo_location_wip_id: '',
  odoo_location_production_id: '',
  odoo_location_fg_id: '',
  odoo_location_scrap_id: '',
  odoo_uom_id: '',
  odoo_picking_type_internal_id: '',
  odoo_payment_journal_id: '',
  reconciliation_tolerance_units: '5',
  reconciliation_tolerance_pct: '0.01',
  reconciliation_alert_wa_to: '',
  active: true,
};

/** PURE — nilai angka/null → string form (`null` → ""). */
function numberToForm(value: number | null): string {
  return value === null ? '' : String(value);
}

/** PURE — baris profil (atau `null`) → nilai form. */
export function integrationConfigFormFromRow(
  row: IntegrationConfigRow | null,
): IntegrationConfigFormValues {
  if (row === null) return { ...EMPTY_INTEGRATION_FORM };

  return {
    erp_adapter: row.erp_adapter === '' ? 'odoo' : row.erp_adapter,
    odoo_url: row.odoo_url,
    odoo_db: row.odoo_db,
    odoo_user: row.odoo_user,
    odoo_api_key: row.odoo_api_key,
    odoo_timeout: numberToForm(row.odoo_timeout),
    odoo_location_wip_id: numberToForm(row.odoo_location_wip_id),
    odoo_location_production_id: numberToForm(row.odoo_location_production_id),
    odoo_location_fg_id: numberToForm(row.odoo_location_fg_id),
    odoo_location_scrap_id: numberToForm(row.odoo_location_scrap_id),
    odoo_uom_id: numberToForm(row.odoo_uom_id),
    odoo_picking_type_internal_id: numberToForm(row.odoo_picking_type_internal_id),
    odoo_payment_journal_id: numberToForm(row.odoo_payment_journal_id),
    reconciliation_tolerance_units: numberToForm(row.reconciliation_tolerance_units),
    reconciliation_tolerance_pct: numberToForm(row.reconciliation_tolerance_pct),
    reconciliation_alert_wa_to: row.reconciliation_alert_wa_to.join(', '),
    active: row.is_active,
  };
}

/** PURE — URL http/https **dengan host** (menerima hostname internal tanpa TLD). */
export function isHttpUrl(value: string): boolean {
  try {
    const url = new URL(value);

    return (url.protocol === 'http:' || url.protocol === 'https:') && url.host !== '';
  } catch {
    return false;
  }
}

/** PURE — daftar nomor WA dari string dipisah koma (item kosong dibuang). */
export function waNumbers(value: string): string[] {
  return value
    .split(',')
    .map((item) => item.trim())
    .filter((item) => item !== '');
}

/** PURE — string id → `number | null` (kosong → `null`). */
export function toNullableInt(value: string): number | null {
  const text = value.trim();

  return text === '' ? null : Number(text);
}

/** PURE — nilai config untuk tampilan (`null`/kosong → "—"). */
export function formatConfigValue(
  value: string | number | number[] | string[] | null,
): string {
  if (value === null || value === '') return '—';
  if (Array.isArray(value)) return value.length === 0 ? '—' : value.join(', ');

  return String(value);
}

/** PURE — True kalau nilai API key adalah mask backend (artinya: jangan diubah). */
export function isMaskedApiKey(value: string): boolean {
  return value.trim() === INTEGRATION_MASK;
}

/** PURE — effective values → baris `{field, label, value}` untuk bagian Status. */
export function effectiveStatusRows(
  effective: IntegrationConfigValues,
): { field: string; label: string; value: string }[] {
  return Object.entries(CONFIG_FIELD_LABELS).map(([field, label]) => ({
    field,
    label,
    value: formatConfigValue(effective[field as keyof IntegrationConfigValues]),
  }));
}

/** Field form bertipe teks (semua kecuali `active`). */
export type IntegrationConfigTextField = Exclude<keyof IntegrationConfigFormValues, 'active'>;

/** Field id Odoo pada form (angka positif atau kosong). */
const ID_FORM_FIELDS = [
  'odoo_location_wip_id',
  'odoo_location_production_id',
  'odoo_location_fg_id',
  'odoo_location_scrap_id',
  'odoo_uom_id',
  'odoo_picking_type_internal_id',
  'odoo_payment_journal_id',
] as const;

/** Validasi form → error per field (cermin `validate_config_payload` backend). */
export function validateIntegrationConfigForm(
  values: IntegrationConfigFormValues,
): IntegrationConfigFormErrors {
  const errors: IntegrationConfigFormErrors = {};

  const adapter = values.erp_adapter.trim().toLowerCase();
  if (!ADAPTER_VALUES.includes(adapter)) {
    errors.erp_adapter = `Adapter harus salah satu dari ${ADAPTER_VALUES.join(', ')}.`;
  }

  const url = values.odoo_url.trim();
  if (url !== '' && !isHttpUrl(url)) {
    errors.odoo_url = 'URL harus http/https (mis. http://odoo:8069).';
  }

  const timeout = Number(values.odoo_timeout);
  if (values.odoo_timeout.trim() === '' || !Number.isFinite(timeout)) {
    errors.odoo_timeout = 'Timeout harus angka (detik).';
  } else if (timeout < MIN_TIMEOUT || timeout > MAX_TIMEOUT) {
    errors.odoo_timeout = `Timeout harus antara ${MIN_TIMEOUT} dan ${MAX_TIMEOUT}.`;
  }

  // guard: adapter 'odoo' wajib punya kredensial (pola backend)
  if (adapter === 'odoo') {
    if (url === '') errors.odoo_url = 'Adapter Odoo membutuhkan URL Odoo.';
    if (values.odoo_db.trim() === '') {
      errors.odoo_db = 'Adapter Odoo membutuhkan database Odoo.';
    }
    if (values.odoo_user.trim() === '') {
      errors.odoo_user = 'Adapter Odoo membutuhkan user Odoo.';
    }
  }

  for (const field of ID_FORM_FIELDS) {
    const text = values[field].trim();
    if (text === '') continue;

    const parsed = Number(text);
    if (!Number.isInteger(parsed) || parsed < 1) {
      errors[field] = 'Id harus angka bulat ≥ 1 (atau dikosongkan).';
    }
  }

  const units = Number(values.reconciliation_tolerance_units);
  if (values.reconciliation_tolerance_units.trim() === '' || !Number.isFinite(units)) {
    errors.reconciliation_tolerance_units = 'Toleransi unit harus angka.';
  } else if (units < 0) {
    errors.reconciliation_tolerance_units = 'Toleransi unit tidak boleh negatif.';
  }

  const pct = Number(values.reconciliation_tolerance_pct);
  if (values.reconciliation_tolerance_pct.trim() === '' || !Number.isFinite(pct)) {
    errors.reconciliation_tolerance_pct = 'Toleransi rasio harus angka.';
  } else if (pct < 0 || pct > MAX_TOLERANCE_PCT) {
    errors.reconciliation_tolerance_pct =
      `Toleransi rasio harus antara 0 dan ${MAX_TOLERANCE_PCT}.`;
  }

  for (const number of waNumbers(values.reconciliation_alert_wa_to)) {
    if (number.length > MAX_WA_LENGTH) {
      errors.reconciliation_alert_wa_to = `Nomor WA maksimal ${MAX_WA_LENGTH} karakter.`;
      break;
    }
  }

  return errors;
}

/** PURE — form valid (tak ada error). */
export function isIntegrationConfigFormValid(errors: IntegrationConfigFormErrors): boolean {
  return Object.keys(errors).length === 0;
}

/** PURE — form → body `PUT` (angka dikonversi; `***` diteruskan apa adanya). */
export function integrationConfigInputFromForm(
  values: IntegrationConfigFormValues,
): IntegrationConfigInput {
  const apiKey = values.odoo_api_key.trim();

  return {
    erp_adapter: values.erp_adapter.trim().toLowerCase(),
    odoo_url: values.odoo_url.trim(),
    odoo_db: values.odoo_db.trim(),
    odoo_user: values.odoo_user.trim(),
    // `***` = jangan ubah (backend mengabaikannya); nilai lain (termasuk "") ganti/hapus.
    odoo_api_key: apiKey === INTEGRATION_MASK ? INTEGRATION_MASK : values.odoo_api_key,
    odoo_timeout: Number(values.odoo_timeout),
    odoo_location_wip_id: toNullableInt(values.odoo_location_wip_id),
    odoo_location_production_id: toNullableInt(values.odoo_location_production_id),
    odoo_location_fg_id: toNullableInt(values.odoo_location_fg_id),
    odoo_location_scrap_id: toNullableInt(values.odoo_location_scrap_id),
    odoo_uom_id: toNullableInt(values.odoo_uom_id),
    odoo_picking_type_internal_id: toNullableInt(values.odoo_picking_type_internal_id),
    odoo_payment_journal_id: toNullableInt(values.odoo_payment_journal_id),
    reconciliation_tolerance_units: Number(values.reconciliation_tolerance_units),
    reconciliation_tolerance_pct: Number(values.reconciliation_tolerance_pct),
    reconciliation_alert_wa_to: waNumbers(values.reconciliation_alert_wa_to),
    active: values.active,
  };
}
