import { useNavigate, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { ArrowLeft, History, Pencil, RefreshCw } from 'lucide-react';
import { Badge } from '@/components/atoms/Badge';
import { Button } from '@/components/atoms/Button';
import { Spinner } from '@/components/atoms/Spinner';
import { Tooltip } from '@/components/atoms/Tooltip';
import { PageHeader } from '@/components/molecules/PageHeader';
import { fetchProduct } from '@/api/masterProducts';
import { useApiClient } from '@/hooks/useApiClient';
import { cn } from '@/lib/cn';
import { productDetailItems } from '@/lib/master-product';
import { CARD } from '@/lib/tokens';

/**
 * ProductDetailPage - route `/master/products/:id` (H1.1, READ-ONLY).
 *
 * Menampilkan satu produk master + jejak sync (`odoo_id` = kunci idempotensi; `null`
 * = belum pernah terkirim ke Odoo). Halaman ini TIDAK menulis apa pun:
 *
 *   * **Edit** → `/master/products/:id/edit` (form yang sama dengan "Produk Baru");
 *   * **Sync ke Odoo** → **placeholder DISABLED** + tooltip "H2": endpoint push manual
 *     (`POST /master/products/<id>/sync/`) belum ada — push saat ini otomatis & asinkron
 *     setiap POST/PUT/DELETE lewat task `erp_sync.push_master_product` (pantau di
 *     `/settings/sync`).
 */

export function ProductDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const client = useApiClient();

  const parsedId = id === undefined ? null : Number(id);
  const productId = parsedId !== null && Number.isFinite(parsedId) ? parsedId : null;

  const { data: product, isLoading, error, refetch } = useQuery({
    queryKey: ['master-product', productId],
    queryFn: () => fetchProduct(client, productId ?? 0),
    enabled: productId !== null,
    staleTime: 15_000,
  });

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title={product === undefined ? 'Detail Produk' : product.name}
        subtitle="Master produk MES (read-only) — gunakan Edit untuk mengubah"
        breadcrumb={[
          { label: 'Inventory', href: '/inventory/products' },
          { label: 'Master Products', href: '/master/products' },
          { label: product === undefined ? 'Detail' : product.code },
        ]}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="secondary"
              icon={ArrowLeft}
              onClick={() => navigate('/master/products')}
            >
              Kembali
            </Button>

            <Button
              icon={Pencil}
              disabled={product === undefined}
              onClick={() => navigate(`/master/products/${String(productId)}/edit`)}
            >
              Edit
            </Button>

            {/* H2 — endpoint push manual belum ada; push otomatis lewat task Celery. */}
            <Tooltip content="Sync manual tersedia di H2 — push sekarang otomatis & asinkron">
              <Button
                variant="secondary"
                icon={RefreshCw}
                disabled
                aria-label="Sync ke Odoo (belum tersedia, H2)"
              >
                Sync ke Odoo
              </Button>
            </Tooltip>
          </div>
        }
      />

      {isLoading ? (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Spinner size="sm" /> Memuat produk…
        </div>
      ) : null}

      {error !== null ? (
        <section className={cn(CARD, 'flex flex-col gap-2')}>
          <p role="alert" className="text-sm font-medium text-accent-coral">
            Gagal memuat produk (perlu login atau produk tidak ada).
          </p>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => {
              void refetch();
            }}
          >
            Coba Lagi
          </Button>
        </section>
      ) : null}

      {product !== undefined ? (
        <>
          <section className={cn(CARD, 'flex flex-wrap items-center gap-3')}>
            <span className="font-mono text-sm font-semibold text-foreground">
              {product.code}
            </span>
            <Badge tone={product.active ? 'blue' : 'muted'}>
              {product.active ? 'Aktif' : 'Nonaktif'}
            </Badge>
            <Badge tone={product.odoo_id === null ? 'coral' : 'blue'}>
              {product.odoo_id === null ? 'Belum sync Odoo' : `Odoo #${String(product.odoo_id)}`}
            </Badge>
          </section>

          <section className={cn(CARD, 'grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3')}>
            {productDetailItems(product).map((item) => (
              <div key={item.label} className="flex flex-col gap-1">
                <span className="text-xs font-medium text-muted-foreground">{item.label}</span>
                <span
                  className={cn(
                    'text-sm text-foreground',
                    item.mono === true ? 'font-mono' : undefined,
                  )}
                >
                  {item.value}
                </span>
              </div>
            ))}
          </section>

          {/* H3.5 — kartu harga: jejak audit perubahan harga (price_updated_at) +
              tautan ke riwayat. Edit harga dilakukan di form produk (H1.1). */}
          <section className={cn(CARD, 'flex flex-col gap-3')}>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex flex-col gap-1">
                <span className="text-xs font-medium text-muted-foreground">
                  Harga terakhir diubah
                </span>
                <span className="text-sm text-foreground">
                  {product.price_updated_at === null
                    ? 'Belum pernah diubah setelah dibuat'
                    : product.price_updated_at}
                </span>
              </div>
              <Button
                variant="secondary"
                size="sm"
                icon={History}
                onClick={() =>
                  navigate(`/master/products/${String(productId)}/price-history`)
                }
              >
                Riwayat Harga
              </Button>
            </div>
          </section>
        </>
      ) : null}
    </div>
  );
}
