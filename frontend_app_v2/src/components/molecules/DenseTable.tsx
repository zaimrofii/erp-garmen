import type { ReactNode } from 'react';
import { AlertOctagon } from 'lucide-react';
import { Button } from '@/components/atoms/Button';
import { Spinner } from '@/components/atoms/Spinner';
import { cn } from '@/lib/cn';
import { TABLE_CELL, TABLE_HEAD } from '@/lib/tokens';

/**
 * DenseTable - tabel padat GENERIC untuk halaman Inventory/Purchase (Fase 20).
 *
 * Satu tempat untuk: header token (`TABLE_HEAD`), sel token (`TABLE_CELL`), hover row,
 * empty/loading/error state, dan `key={row.id}` (larangan `key={index}`).
 *
 * `render` opsional per kolom: tanpa `render`, nilai dibaca dari properti `row` lewat
 * `Object.entries()` (TANPA cast `as`, jadi tipe tetap strict).
 */

export type DenseTableAlign = 'left' | 'right' | 'center';

export interface DenseTableColumn<T> {
  key: string;
  label: string;
  align?: DenseTableAlign;
  render?: (row: T) => ReactNode;
  className?: string;
}

const ALIGN_CLASS: Record<DenseTableAlign, string> = {
  left: '',
  right: 'text-right',
  center: 'text-center',
};

function readCell(row: object, key: string): unknown {
  return new Map(Object.entries(row)).get(key);
}

function formatCell(value: unknown): string {
  if (value === null || value === undefined) return '-';
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);

  return JSON.stringify(value) ?? '-';
}

interface DenseTableProps<T extends object> {
  columns: DenseTableColumn<T>[];
  rows: T[];
  loading?: boolean;
  error?: string | null;
  onRetry?: () => void;
  onRowClick?: (row: T) => void;
  emptyMessage?: string;
  className?: string;
  /** Kunci baris kustom kalau `row.id` tidak ada (fallback: index). */
  rowKey?: (row: T) => number | string;
}

export function DenseTable<T extends object>({
  columns,
  rows,
  loading = false,
  error = null,
  onRetry,
  onRowClick,
  emptyMessage = 'Belum ada data.',
  className,
  rowKey,
}: DenseTableProps<T>) {
  const hasError = error !== null;
  const showRows = !loading && !hasError;

  return (
    <div className={cn('overflow-x-auto', className)}>
      <table className="w-full border-collapse" aria-busy={loading || undefined}>
        <thead>
          <tr className="border-b border-border/80">
            {columns.map((column) => (
              <th
                key={column.key}
                scope="col"
                className={cn(
                  TABLE_HEAD,
                  column.align === undefined ? undefined : ALIGN_CLASS[column.align],
                  column.className,
                )}
              >
                {column.label}
              </th>
            ))}
          </tr>
        </thead>

        <tbody>
          {loading ? (
            <tr>
              <td colSpan={columns.length} className="p-6 text-center">
                <Spinner size="md" />
              </td>
            </tr>
          ) : null}

          {!loading && hasError ? (
            <tr>
              <td colSpan={columns.length} className="p-6">
                <div className="flex flex-col items-center gap-3">
                  <p
                    role="alert"
                    className="flex items-center gap-2 text-sm font-medium text-accent-coral"
                  >
                    <AlertOctagon className="h-4 w-4 shrink-0" aria-hidden="true" />
                    {error}
                  </p>
                  {onRetry !== undefined ? (
                    <Button variant="secondary" size="sm" onClick={onRetry}>
                      Coba Lagi
                    </Button>
                  ) : null}
                </div>
              </td>
            </tr>
          ) : null}

          {showRows && rows.length === 0 ? (
            <tr>
              <td colSpan={columns.length} className="p-6 text-center text-sm text-muted-foreground">
                {emptyMessage}
              </td>
            </tr>
          ) : null}

          {showRows
            ? rows.map((row, index) => (
                <tr
                  key={rowKey === undefined ? ((row as { id?: number | string }).id ?? index) : rowKey(row)}
                  onClick={onRowClick === undefined ? undefined : () => onRowClick(row)}
                  className={cn(
                    'transition-colors',
                    onRowClick !== undefined ? 'cursor-pointer hover:bg-muted/50' : 'hover:bg-muted/30',
                  )}
                >
                  {columns.map((column) => (
                    <td
                      key={column.key}
                      className={cn(
                        TABLE_CELL,
                        column.align === undefined ? undefined : ALIGN_CLASS[column.align],
                        column.className,
                      )}
                    >
                      {column.render !== undefined
                        ? column.render(row)
                        : formatCell(readCell(row, column.key))}
                    </td>
                  ))}
                </tr>
              ))
            : null}
        </tbody>
      </table>
    </div>
  );
}
