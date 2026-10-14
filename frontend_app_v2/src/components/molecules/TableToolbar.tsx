import { useEffect, useRef, useState } from 'react';
import { Download, RefreshCw, Search } from 'lucide-react';
import { Button } from '@/components/atoms/Button';
import { Input } from '@/components/atoms/Input';
import { Tabs } from '@/components/atoms/Tabs';
import { cn } from '@/lib/cn';

/**
 * TableToolbar - toolbar tabel dense: search + filter chips + Export CSV + Refresh.
 *
 * Search di-DEBOUNCE 300 ms (`SEARCH_DEBOUNCE_MS`): input tetap responsif (state lokal
 * `draft`), sedangkan `onSearchChange` dipanggil setelah user berhenti mengetik - jadi
 * pemanggil cukup mereset pagination di dalam handler-nya, tanpa useMemo/useEffect.
 */

export const SEARCH_DEBOUNCE_MS = 300;

interface TableToolbarProps {
  search: string;
  onSearchChange: (value: string) => void;
  searchPlaceholder?: string;
  searchLabel?: string;
  filters?: { id: string; label: string }[];
  activeFilter?: string;
  onFilterChange?: (id: string) => void;
  onExport?: () => void;
  onRefresh?: () => void;
  exportDisabled?: boolean;
  refreshing?: boolean;
  className?: string;
}

export function TableToolbar({
  search,
  onSearchChange,
  searchPlaceholder = 'Cari...',
  searchLabel = 'Cari',
  filters,
  activeFilter,
  onFilterChange,
  onExport,
  onRefresh,
  exportDisabled = false,
  refreshing = false,
  className,
}: TableToolbarProps) {
  const [draft, setDraft] = useState(search);
  const timerRef = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    };
  }, []);

  function handleSearch(value: string): void {
    setDraft(value);

    if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    timerRef.current = window.setTimeout(() => {
      timerRef.current = null;
      onSearchChange(value);
    }, SEARCH_DEBOUNCE_MS);
  }

  const showFilters =
    filters !== undefined && filters.length > 0 && onFilterChange !== undefined;

  return (
    <div
      className={cn(
        'flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between',
        className,
      )}
    >
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
        <div className="w-full sm:w-64">
          <Input
            label={searchLabel}
            icon={Search}
            value={draft}
            placeholder={searchPlaceholder}
            onChange={(event) => handleSearch(event.target.value)}
          />
        </div>

        {showFilters ? (
          <Tabs
            tabs={filters}
            active={activeFilter ?? filters[0].id}
            onChange={onFilterChange}
          />
        ) : null}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {onExport !== undefined ? (
          <Button
            variant="secondary"
            size="sm"
            icon={Download}
            disabled={exportDisabled}
            onClick={onExport}
          >
            Export CSV
          </Button>
        ) : null}

        {onRefresh !== undefined ? (
          <Button
            variant="secondary"
            size="sm"
            icon={RefreshCw}
            loading={refreshing}
            onClick={onRefresh}
          >
            Refresh
          </Button>
        ) : null}
      </div>
    </div>
  );
}
