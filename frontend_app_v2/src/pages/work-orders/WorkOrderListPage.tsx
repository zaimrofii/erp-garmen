import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useWorkOrders } from '@/hooks/useWorkOrders';
import { StatusChip } from '@/components/molecules/StatusChip';
import { Spinner } from '@/components/atoms/Spinner';
import { Button } from '@/components/atoms/Button';
import { chipStatusFromState } from '@/lib/state-display';

const PAGE_SIZE = 20;

export function WorkOrderListPage() {
  const [offset, setOffset] = useState(0);
  const { data, isLoading, error } = useWorkOrders({ limit: PAGE_SIZE, offset });

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
        <p className="text-danger">Gagal memuat work order.</p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-3xl space-y-3 p-4">
      <h1 className="text-lg font-semibold text-foreground">Work Order</h1>

      {/* H2.3 — pintu masuk form WO (nomor otomatis Sprint C; MES-only). */}
      <div className="flex flex-wrap items-center gap-2">
        <Link to="/production/work-orders/new">
          <Button size="sm">Buat WO Baru</Button>
        </Link>
        <span className="text-xs text-muted-foreground">
          Satu WO = satu baris order; pecahan lebih lanjut lewat tombol Split di detail.
        </span>
      </div>

      <ul className="divide-y divide-border rounded-card border border-border bg-card shadow-soft-card">
        {data.rows.map((row) => (
          <li key={row.id} className="flex items-center justify-between gap-2 p-3">
            <div>
              <span className="font-medium text-foreground">{String(row.code ?? row.id)}</span>
              <div className="mt-1 text-xs text-muted-foreground">
                {String(row.qty_done ?? 0)} / {String(row.qty_planned ?? 0)}
              </div>
            </div>
            <StatusChip
              status={chipStatusFromState(String(row.state ?? ''))}
              label={String(row.state ?? '-')}
            />
          </li>
        ))}
      </ul>

      {data.rows.length === 0 ? (
        <p className="text-sm text-muted-foreground">Belum ada work order.</p>
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
