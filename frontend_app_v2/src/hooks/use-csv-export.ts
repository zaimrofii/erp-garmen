import { useCallback } from 'react';

/**
 * use-csv-export.ts - export CSV tanpa library (Fase 20).
 *
 * Semua nilai dibaca lewat `Object.entries()` (tanpa cast `as`) sehingga aman untuk
 * tipe apa pun. Field yang mengandung koma/quote/newline di-escape sesuai RFC 4180
 * (dibungkus `"` dan quote di-double).
 *
 * CATATAN: `exportCsv()` mendelegasikan ke `downloadCsv()` di browser (Blob + object URL);
 * dipakai sebagai hook supaya nanti bisa ditambah opsi (delimiter, BOM untuk Excel,
 * nama file berpola) tanpa mengubah 7 halaman yang memakainya.
 */

export interface CsvColumn<T> {
  key: keyof T & string;
  label: string;
}

const NEEDS_ESCAPE = /[",\n\r]/;

export function escapeCsvField(value: unknown): string {
  if (value === null || value === undefined) return '';

  const text =
    typeof value === 'string'
      ? value
      : typeof value === 'number' || typeof value === 'boolean'
        ? String(value)
        : (JSON.stringify(value) ?? '');

  return NEEDS_ESCAPE.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

function readField(row: object, key: string): unknown {
  return new Map(Object.entries(row)).get(key);
}

/** PURE - baris -> teks CSV. Tanpa `columns`, header diambil dari key baris pertama. */
export function buildCsv<T extends object>(rows: readonly T[], columns?: readonly CsvColumn<T>[]): string {
  const first = rows[0];
  const resolved: { key: string; label: string }[] =
    columns !== undefined
      ? columns.map((column) => ({ key: column.key, label: column.label }))
      : first === undefined
        ? []
        : Object.keys(first).map((key) => ({ key, label: key }));

  const header = resolved.map((column) => escapeCsvField(column.label)).join(',');
  const lines = rows.map((row) =>
    resolved.map((column) => escapeCsvField(readField(row, column.key))).join(','),
  );

  return [header, ...lines].join('\n');
}

/** Dipanggil di browser; no-op kalau tidak ada DOM (ssr/test). */
export function downloadCsv(content: string, filename: string): void {
  if (typeof document === 'undefined') return;

  const blob = new Blob([content], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');

  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export interface UseCsvExportResult {
  exportCsv: <T extends object>(
    rows: readonly T[],
    filename: string,
    columns?: readonly CsvColumn<T>[],
  ) => void;
}

export function useCsvExport(): UseCsvExportResult {
  const exportCsv = useCallback(
    <T extends object>(rows: readonly T[], filename: string, columns?: readonly CsvColumn<T>[]): void => {
      downloadCsv(buildCsv(rows, columns), filename);
    },
    [],
  );

  return { exportCsv };
}
