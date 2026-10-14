import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Button } from '@/components/atoms/Button';
import { Input } from '@/components/atoms/Input';
import { Select } from '@/components/atoms/Select';
import { Spinner } from '@/components/atoms/Spinner';
import { PageHeader } from '@/components/molecules/PageHeader';
import { StatusChip } from '@/components/molecules/StatusChip';
import { fetchAdjustments, INVENTORY_ADJUSTMENTS_LIMIT_MAX } from '@/api/inventoryAdjustments';
import { fetchLocations } from '@/api/masterLocations';
import { fetchProducts } from '@/api/masterProducts';
import { useApiClient } from '@/hooks/useApiClient';
import { adjustmentStateLabel, adjustmentChipStatus, signedDelta } from '@/lib/inventory-adjustment';
import { CARD } from '@/lib/tokens';

const PAGE_SIZE = 20;
const ALL_OPTION = { value: '', label: '— Semua —' };
const STATE_OPTIONS = [
  ALL_OPTION,
  { value: 'DRAFT', label: 'Draft' },
  { value: 'COMMITTED', label: 'Dikirim (menunggu)' },
  { value: 'SYNCED', label: 'Tersinkron' },
  { value: 'FAILED', label: 'Gagal' },
];

/**
 * InventoryAdjustmentListPage — route `/inventory/adjustments` (H2.5).
 *
 * **Audit log** adjustment stok MES → Odoo: filter (`search`/`state`/produk/lokasi)
 * + paging. MES tidak menyimpan stok, jadi halaman ini tidak menampilkan saldo —
 * saldo hanya dibaca on-demand di form (`/inventory/adjust`).
 */
export function InventoryAdjustmentListPage() {
  const client = useApiClient();
  const [offset, setOffset] = useState(0);
  const [search, setSearch] = useState('');
  const [state, setState] = useState('');
  const [productId, setProductId] = useState('');
  const [locationId, setLocationId] = useState('');

  const query = useQuery({
    queryKey: ['inventory-adjustments', search, state, productId, locationId, offset],
    queryFn: () =>
      fetchAdjustments(client, {
        search: search.trim().length === 0 ? null : search.trim(),
        state: state.length === 0 ? null : state,
        product_id: productId.length === 0 ? null : Number(productId),
        location_id: locationId.length === 0 ? null : Number(locationId),
        limit: PAGE_SIZE,
        offset,
      }),
    staleTime: 15_000,
  });

  const products = useQuery({
    queryKey: ['master-products', 'inventory-adjust-options'],
    queryFn: () => fetchProducts(client, { limit: INVENTORY_ADJUSTMENTS_LIMIT_MAX }),
    staleTime: 60_000,
  });
  const locations = useQuery({
    queryKey: ['master-locations', 'inventory-adjust-options'],
    queryFn: () => fetchLocations(client, { limit: INVENTORY_ADJUSTMENTS_LIMIT_MAX }),
    staleTime: 60_000,
  });

  const productOptions = useMemo(
    () => [
      ALL_OPTION,
      ...(products.data?.rows ?? []).map((row) => ({ value: String(row.id), label: row.code })),
    ],
    [products.data],
  );
  const locationOptions = useMemo(
    () => [
      ALL_OPTION,
      ...(locations.data?.rows ?? [])
        .filter((row) => row.usage === 'internal')
        .map((row) => ({ value: String(row.id), label: row.code })),
    ],
    [locations.data],
  );

  /** Reset paging saat filter berubah (biar tidak "nyangkut" di halaman jauh). */
  function updateFilter(setter: (value: string) => void, value: string) {
    setter(value);
    setOffset(0);
  }

  if (query.isLoading && query.data === undefined) {
    return (
      <div className="p-4">
        <Spinner />
      </div>
    );
  }
  if (query.error !== null || query.data === undefined) {
    return (
      <div className="p-4">
        <p className="text-danger">Gagal memuat daftar inventory adjustment.</p>
      </div>
    );
  }

  const data = query.data;

  return (
    <div className="mx-auto max-w-3xl space-y-3 p-4">
      <PageHeader
        title="Inventory Adjustment"
        subtitle="Log penyesuaian stok MES → Odoo (stok tetap milik Odoo)."
        actions={
          <Link to="/inventory/adjust">
            <Button size="sm">Buat Adjustment</Button>
          </Link>
        }
      />

      <div className={`${CARD} space-y-2`}>
        <Input
          label="Cari (kode / alasan)"
          value={search}
          onChange={(event) => updateFilter(setSearch, event.target.value)}
          placeholder="ADJ-2026-0001"
        />
        <div className="grid gap-2 sm:grid-cols-3">
          <Select
            label="State"
            options={STATE_OPTIONS}
            value={state}
            onChange={(event) => updateFilter(setState, event.target.value)}
          />
          <Select
            label="Produk"
            options={productOptions}
            value={productId}
            onChange={(event) => updateFilter(setProductId, event.target.value)}
          />
          <Select
            label="Lokasi (internal)"
            options={locationOptions}
            value={locationId}
            onChange={(event) => updateFilter(setLocationId, event.target.value)}
          />
        </div>
      </div>

      <ul className="divide-y divide-border rounded-card border border-border bg-card shadow-soft-card">
        {data.rows.map((row) => (
          <li key={row.id} className="p-3">
            <Link
              to={`/inventory/adjustments/${String(row.id)}`}
              className="flex items-center justify-between gap-2"
            >
              <span className="font-medium text-foreground">{row.code}</span>
              <StatusChip
                status={adjustmentChipStatus(row.state)}
                label={adjustmentStateLabel(row.state)}
              />
            </Link>
            <div className="mt-1 text-xs text-muted-foreground">
              {row.product_code ?? '—'} @ {row.location_code ?? '—'} ·{' '}
              {signedDelta(row.qty_delta)} · {adjustmentStateLabel(row.state)}
            </div>
          </li>
        ))}
      </ul>

      {data.rows.length === 0 ? (
        <p className="text-sm text-muted-foreground">Belum ada adjustment.</p>
      ) : null}

      <div className="flex items-center justify-between">
        <span className="text-xs text-muted-foreground">
          {data.rows.length} dari {data.total_count}
        </span>
        {data.has_more ? (
          <Button variant="secondary" onClick={() => setOffset((value) => value + PAGE_SIZE)}>
            Muat lebih banyak
          </Button>
        ) : null}
      </div>
    </div>
  );
}
