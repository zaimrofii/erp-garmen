import { useCallback, useMemo, useState } from 'react';

/**
 * use-pagination.ts - pagination OFFSET-based untuk tabel dense (Fase 20).
 *
 * DESAIN: hook menerima `rows` yang SUDAH difilter, jadi `total` = `rows.length`
 * (turunan, bukan state). Ini menghindari `setState` di dalam render/effect (yang
 * memicu warning `react/set-state-in-effect`) dan otomatis menyesuaikan diri saat
 * filter menyisakan lebih sedikit baris - `page` di-clamp ke `totalPages`.
 *
 * CATATAN: adapter DUMMY mengembalikan SELURUH baris (array), belum
 * `{rows, total_count, has_more}` seperti kontrak backend, jadi pagination di sini
 * **client-side** (`slice`). Saat backend siap: ganti `pageRows` dengan data dari server
 * dan tambahkan `total` dari `total_count` - sisa API hook tidak perlu berubah.
 */

export const DEFAULT_PAGE_SIZE = 20;

export interface UsePaginationOptions {
  pageSize?: number;
  initialPage?: number;
}

export interface UsePaginationResult<T> {
  /** Halaman aktif (sudah di-clamp ke rentang valid). */
  page: number;
  setPage: (page: number) => void;
  pageSize: number;
  /** Jumlah baris setelah filter (client-side). */
  total: number;
  totalPages: number;
  /** Baris untuk halaman aktif. */
  pageRows: T[];
  /** 1-based; 0 kalau total 0. */
  rangeStart: number;
  rangeEnd: number;
  canPrev: boolean;
  canNext: boolean;
  goPrev: () => void;
  goNext: () => void;
  /** Reset ke halaman 1 - dipanggil halaman saat search/filter berubah. */
  reset: () => void;
}

export function usePagination<T>(
  rows: readonly T[],
  options: UsePaginationOptions = {},
): UsePaginationResult<T> {
  const pageSize = options.pageSize ?? DEFAULT_PAGE_SIZE;

  const [requestedPage, setRequestedPage] = useState(options.initialPage ?? 1);

  const total = rows.length;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const page = Math.min(Math.max(1, requestedPage), totalPages);

  const setPage = useCallback((next: number): void => {
    setRequestedPage(Math.max(1, Math.trunc(next)));
  }, []);

  const reset = useCallback((): void => {
    setRequestedPage(1);
  }, []);

  const goPrev = useCallback((): void => {
    setRequestedPage((current) => Math.max(1, current - 1));
  }, []);

  const goNext = useCallback((): void => {
    setRequestedPage((current) => current + 1);
  }, []);

  const pageRows = useMemo(
    () => rows.slice((page - 1) * pageSize, page * pageSize),
    [rows, page, pageSize],
  );

  return {
    page,
    setPage,
    pageSize,
    total,
    totalPages,
    pageRows: [...pageRows],
    rangeStart: total === 0 ? 0 : (page - 1) * pageSize + 1,
    rangeEnd: Math.min(page * pageSize, total),
    canPrev: page > 1,
    canNext: page < totalPages,
    goPrev,
    goNext,
    reset,
  };
}

