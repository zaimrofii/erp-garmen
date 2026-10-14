import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useBundles } from '@/hooks/useBundles';
import { StatusChip } from '@/components/molecules/StatusChip';
import { Spinner } from '@/components/atoms/Spinner';
import { Button } from '@/components/atoms/Button';
import { chipStatusFromState } from '@/lib/state-display';

const PAGE_SIZE = 20;

export function BundleListPage() {
  const [offset, setOffset] = useState(0);
  const { data, isLoading, error } = useBundles({ limit: PAGE_SIZE, offset });

  if (isLoading && data === undefined) {
    return (
      <div className="p-4">
        <Spinner />
      </div>
    );
  }
  if (error || data === undefined) {
    return (
      <div className="p-4">
        <p className="text-danger">Gagal memuat daftar bundle.</p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-3xl space-y-3 p-4">
      <h1 className="text-lg font-semibold text-foreground">Daftar Bundle</h1>

      {/* H2.4 — pintu masuk form bundle (matriks ukuran; MES-only). ADITIF. */}
      <div className="flex flex-wrap items-center gap-2">
        <Link to="/production/bundles/new">
          <Button size="sm">Buat Bundle</Button>
        </Link>
        <span className="text-xs text-muted-foreground">
          Kelola (ubah/split/merge/hapus) lewat halaman bundle.
        </span>
      </div>

      <ul className="divide-y divide-border rounded-card border border-border bg-card shadow-soft-card">
        {data.rows.map((row) => (
          <li key={row.id} className="p-3">
            <Link to={`/bundles/${row.id}`} className="flex items-center justify-between gap-2">
              <span className="font-medium text-foreground">{String(row.code ?? row.id)}</span>
              <StatusChip
                status={chipStatusFromState(String(row.state ?? ''))}
                label={String(row.state ?? '-')}
              />
            </Link>
            <div className="mt-1 text-xs text-muted-foreground">
              {String(row.size ?? '—')} · {String(row.qty_done ?? 0)} / {String(row.qty ?? 0)} ·{' '}
              {String(row.current_work_center_code ?? '—')}
            </div>
          </li>
        ))}
      </ul>

      {data.rows.length === 0 ? (
        <p className="text-sm text-muted-foreground">Belum ada bundle.</p>
      ) : null}

      <div className="flex items-center justify-between">
        <span className="text-xs text-muted-foreground">
          {data.rows.length} dari {data.total_count}
        </span>
        {data.has_more ? (
          <Button variant="secondary" onClick={() => setOffset((o) => o + PAGE_SIZE)}>
            Muat lebih banyak
          </Button>
        ) : null}
      </div>
    </div>
  );
}
