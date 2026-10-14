import { useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { ArrowLeft, RefreshCw } from 'lucide-react';
import { Button } from '@/components/atoms/Button';
import { Spinner } from '@/components/atoms/Spinner';
import { PageHeader } from '@/components/molecules/PageHeader';
import { fetchProduct, fetchProductPriceHistory, PRODUCTS_LIMIT_DEFAULT } from '@/api/masterProducts';
import { useApiClient } from '@/hooks/useApiClient';
import { cn } from '@/lib/cn';
import { displayOrDash, priceHistoryItems } from '@/lib/master-product';
import { CARD } from '@/lib/tokens';

/**
 * ProductPriceHistoryPage — route `/master/products/:id/price-history` (H3.5).
 *
 * **Read-only**: menampilkan riwayat perubahan harga produk dari `AuditLog` backend
 * (action `master.update_price`) — nilai lama → baru, sumber perubahan (endpoint harga
 * atau form produk), user, dan waktu. Riwayat ditulis SETIAP perubahan harga
 * (endpoint `PUT /master/products/<id>/price/` maupun `PUT` produk umum).
 */

export function ProductPriceHistoryPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const client = useApiClient();
  const [cursor, setCursor] = useState(0);

  const parsedId = id === undefined ? null : Number(id);
  const productId = parsedId !== null && Number.isFinite(parsedId) ? parsedId : null;

  const product = useQuery({
    queryKey: ['master-product', productId],
    queryFn: () => fetchProduct(client, productId ?? 0),
    enabled: productId !== null,
    staleTime: 15_000,
  });

  const history = useQuery({
    queryKey: ['master-product-price-history', productId, cursor],
    queryFn: () =>
      fetchProductPriceHistory(client, productId ?? 0, {
        limit: PRODUCTS_LIMIT_DEFAULT,
        cursor,
      }),
    enabled: productId !== null,
    staleTime: 10_000,
  });

  const rows = history.data?.rows ?? [];

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title="Riwayat Harga"
        subtitle={
          product.data === undefined
            ? 'Perubahan harga produk (audit trail)'
            : `${product.data.name} (${product.data.code}) — audit trail perubahan harga`
        }
        breadcrumb={[
          { label: 'Master Products', href: '/master/products' },
          {
            label: product.data === undefined ? 'Produk' : product.data.code,
            href: `/master/products/${String(productId)}`,
          },
          { label: 'Riwayat Harga' },
        ]}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="secondary"
              icon={ArrowLeft}
              onClick={() => navigate(`/master/products/${String(productId)}`)}
            >
              Kembali
            </Button>
            <Button
              variant="secondary"
              icon={RefreshCw}
              onClick={() => {
                void history.refetch();
              }}
            >
              Muat Ulang
            </Button>
          </div>
        }
      />

      {history.isLoading && history.data === undefined ? (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Spinner size="sm" /> Memuat riwayat harga…
        </div>
      ) : null}

      {history.error !== null ? (
        <section className={cn(CARD, 'flex flex-col gap-2')}>
          <p role="alert" className="text-sm font-medium text-accent-coral">
            Gagal memuat riwayat harga (perlu login atau produk tidak ada).
          </p>
        </section>
      ) : null}

      {history.data !== undefined && rows.length === 0 ? (
        <section className={cn(CARD, 'flex flex-col gap-2')}>
          <p className="text-sm text-muted-foreground">
            Belum ada perubahan harga yang tercatat setelah produk dibuat.
          </p>
        </section>
      ) : null}

      {rows.map((row) => (
        <section key={row.id} className={cn(CARD, 'grid grid-cols-1 gap-4 sm:grid-cols-2')}>
          {priceHistoryItems(row).map((item) => (
            <div key={item.label} className="flex flex-col gap-1">
              <span className="text-xs font-medium text-muted-foreground">{item.label}</span>
              <span
                className={cn(
                  'text-sm text-foreground',
                  item.mono === true ? 'font-mono' : undefined,
                )}
              >
                {displayOrDash(item.value)}
              </span>
            </div>
          ))}
        </section>
      ))}

      {history.data !== undefined && history.data.total_count > 0 ? (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <span className="text-xs text-muted-foreground">
            {rows.length} dari {history.data.total_count}
          </span>
          {history.data.has_more ? (
            <Button
              variant="secondary"
              onClick={() => setCursor(history.data?.next_cursor ?? cursor + PRODUCTS_LIMIT_DEFAULT)}
            >
              Muat lebih banyak
            </Button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}