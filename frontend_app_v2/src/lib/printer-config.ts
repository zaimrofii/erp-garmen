/**
 * printer-config.ts — logic PURE halaman Printer Config (H5.7).
 *
 * Dipisah dari halaman supaya bisa diuji TANPA DOM (jsdom tidak jalan di bun —
 * `.clinerules` §ENVIRONMENT): validasi form (6 field + guard kondisional), konversi
 * form ↔ payload PUT, penentuan field yang **tampil** per backend, dan helper tampilan
 * untuk bagian **Status** (effective/diverges).
 *
 * Cermin `master/printer_config_services.py`: ``usb`` ⇒ vendor+product wajib;
 * ``network`` ⇒ host+port (1..65535) wajib; ``mock`` ⇒ folder opsional. **Tanpa mask**
 * (bukan data rahasia) — beda dari H5.6/H5.8.
 */
import type { SelectOption } from '@/components/atoms/Select';
import type {
  PrinterConfigInput,
  PrinterConfigRow,
  PrinterConfigValues,
} from '@/types/printer-config';
import {
  PRINTER_BACKENDS,
  PRINTER_MAX_DIR,
  PRINTER_MAX_HOST,
  PRINTER_MAX_PRODUCT,
  PRINTER_MAX_VENDOR,
  PRINTER_PORT_MAX,
  PRINTER_PORT_MIN,
} from '@/types/printer-config';

/** Opsi dropdown backend printer (+ keterangan singkat di label). */
export const BACKEND_OPTIONS: SelectOption[] = [
  { value: 'mock', label: 'Mock (file .bin, tanpa printer)' },
  { value: 'usb', label: 'USB (stub: butuh python-escpos + libusb)' },
  { value: 'network', label: 'Network (TCP raw, mis. port 9100)' },
];

/** Backend yang wajib punya kredensial/alamat (guard kondisional). */
export const GUARDED_BACKENDS = ['usb', 'network'];

/** Label ramah per field (dipakai form + bagian Status/diverges). */
export const CONFIG_FIELD_LABELS: Record<string, string> = {
  printer_backend: 'Backend printer',
  printer_usb_vendor_id: 'USB vendor id',
  printer_usb_product_id: 'USB product id',
  printer_network_host: 'Host printer',
  printer_network_port: 'Port printer',
  printer_mock_dir: 'Folder mock',
};

/** Field form milik tiap blok kondisional (dipakai form + validasi + test). */
export const BACKEND_FIELDS: Record<string, string[]> = {
  usb: ['printer_usb_vendor_id', 'printer_usb_product_id'],
  network: ['printer_network_host', 'printer_network_port'],
  mock: ['printer_mock_dir'],
};

/** PURE — True kalau nilai backend termasuk yang dikenal (``mock``/``usb``/``network``). */
export function isKnownBackend(value: string): boolean {
  return (PRINTER_BACKENDS as readonly string[]).includes(value.trim().toLowerCase());
}

/**
 * PURE — blok field yang **tampil** untuk sebuah backend.
 *
 * Halaman menyembunyikan field yang tidak relevan supaya operator tidak salah isi
 * (mis. host/port saat backend ``mock``), tetapi nilai lama di DB **tidak** dihapus.
 */
export function visibleFieldGroups(backend: string): {
  usb: boolean;
  network: boolean;
  mock: boolean;
} {
  const name = backend.trim().toLowerCase();

  return {
    usb: name === 'usb',
    network: name === 'network',
    mock: name === 'mock' || name === '',
  };
}

/** Nilai form (semua input = string; `active` = flag). */
export interface PrinterConfigFormValues {
  printer_backend: string;
  printer_usb_vendor_id: string;
  printer_usb_product_id: string;
  printer_network_host: string;
  printer_network_port: string;
  printer_mock_dir: string;
  active: boolean;
}

/** Pesan error per field (kosong = valid). */
export type PrinterConfigFormErrors = Partial<Record<keyof PrinterConfigFormValues, string>>;

/** Nilai awal form (profil belum pernah diisi). */
export const EMPTY_PRINTER_FORM: PrinterConfigFormValues = {
  printer_backend: 'mock',
  printer_usb_vendor_id: '',
  printer_usb_product_id: '',
  printer_network_host: '',
  printer_network_port: '',
  printer_mock_dir: '',
  active: true,
};

/** PURE — angka/null → string form (``null`` → ""). */
function numberToForm(value: number | null): string {
  return value === null ? '' : String(value);
}

/** PURE — baris profil (atau `null`) → nilai form. */
export function printerConfigFormFromRow(row: PrinterConfigRow | null): PrinterConfigFormValues {
  if (row === null) return { ...EMPTY_PRINTER_FORM };

  return {
    printer_backend: row.printer_backend === '' ? 'mock' : row.printer_backend,
    printer_usb_vendor_id: row.printer_usb_vendor_id,
    printer_usb_product_id: row.printer_usb_product_id,
    printer_network_host: row.printer_network_host,
    printer_network_port: numberToForm(row.printer_network_port),
    printer_mock_dir: row.printer_mock_dir,
    active: row.is_active,
  };
}

/** PURE — string port → `number | null` (kosong → ``null``; bukan angka → ``null``). */
export function toNullablePort(value: string): number | null {
  const text = value.trim();
  if (text === '') return null;

  const parsed = Number(text);

  return Number.isInteger(parsed) ? parsed : null;
}

/** PURE — nilai config untuk tampilan (``null``/kosong → "—"). */
export function formatConfigValue(value: string | number | null): string {
  if (value === null || value === '') return '—';

  return String(value);
}

/** PURE — effective values → baris `{field, label, value}` untuk bagian Status. */
export function effectiveStatusRows(
  effective: PrinterConfigValues,
): { field: string; label: string; value: string }[] {
  return Object.entries(CONFIG_FIELD_LABELS).map(([field, label]) => ({
    field,
    label,
    value: formatConfigValue(effective[field as keyof PrinterConfigValues]),
  }));
}

/** PURE — form → body `PUT` (teks di-trim; port dikonversi angka/``null``). */
export function printerConfigInputFromForm(
  values: PrinterConfigFormValues,
): PrinterConfigInput {
  return {
    printer_backend: values.printer_backend.trim().toLowerCase(),
    printer_usb_vendor_id: values.printer_usb_vendor_id.trim(),
    printer_usb_product_id: values.printer_usb_product_id.trim(),
    printer_network_host: values.printer_network_host.trim(),
    printer_network_port: toNullablePort(values.printer_network_port),
    printer_mock_dir: values.printer_mock_dir.trim(),
    active: values.active,
  };
}

/** Validasi form → error per field (cermin `validate_config_payload` backend). */
export function validatePrinterConfigForm(
  values: PrinterConfigFormValues,
): PrinterConfigFormErrors {
  const errors: PrinterConfigFormErrors = {};

  const backend = values.printer_backend.trim().toLowerCase();
  if (!isKnownBackend(backend)) {
    errors.printer_backend = `Backend harus salah satu dari ${PRINTER_BACKENDS.join(', ')}.`;
  }

  const textFields: {
    field: keyof PrinterConfigFormValues;
    label: string;
    max: number;
  }[] = [
    { field: 'printer_usb_vendor_id', label: 'USB vendor id', max: PRINTER_MAX_VENDOR },
    { field: 'printer_usb_product_id', label: 'USB product id', max: PRINTER_MAX_PRODUCT },
    { field: 'printer_network_host', label: 'Host printer', max: PRINTER_MAX_HOST },
    { field: 'printer_mock_dir', label: 'Folder mock', max: PRINTER_MAX_DIR },
  ];

  for (const { field, label, max } of textFields) {
    const raw = values[field];

    if (typeof raw === 'string' && raw.trim().length > max) {
      errors[field] = `${label} maksimal ${String(max)} karakter.`;
    }
  }

  const portText = values.printer_network_port.trim();
  if (portText !== '') {
    const port = Number(portText);

    if (!Number.isInteger(port)) {
      errors.printer_network_port = 'Port harus angka bulat (atau dikosongkan).';
    } else if (port < PRINTER_PORT_MIN || port > PRINTER_PORT_MAX) {
      errors.printer_network_port = `Port harus antara ${String(PRINTER_PORT_MIN)} dan ${String(PRINTER_PORT_MAX)}.`;
    }
  }

  // guard kondisional (pola backend): nilai efektif = form apa adanya
  if (backend === 'usb') {
    if (values.printer_usb_vendor_id.trim() === '') {
      errors.printer_usb_vendor_id = 'Backend usb membutuhkan USB vendor id.';
    }
    if (values.printer_usb_product_id.trim() === '') {
      errors.printer_usb_product_id = 'Backend usb membutuhkan USB product id.';
    }
  }

  if (backend === 'network') {
    if (values.printer_network_host.trim() === '') {
      errors.printer_network_host = 'Backend network membutuhkan host printer.';
    }
    if (portText === '') {
      errors.printer_network_port = 'Backend network membutuhkan port printer.';
    }
  }

  return errors;
}

/** PURE — form valid (tak ada error). */
export function isPrinterConfigFormValid(errors: PrinterConfigFormErrors): boolean {
  return Object.keys(errors).length === 0;
}

