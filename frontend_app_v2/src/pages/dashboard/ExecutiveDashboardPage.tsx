import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  AlertTriangle,
  Layers,
  Package,
  RefreshCw,
  ShoppingCart,
  TrendingDown,
  TrendingUp,
  Wallet,
} from 'lucide-react';
import { Button } from '@/components/atoms/Button';
import { Input } from '@/components/atoms/Input';
import { ExportButton } from '@/components/molecules/ExportButton';
import { KpiCard } from '@/components/molecules/KpiCard';
import { PageHeader } from '@/components/molecules/PageHeader';
import { fetchExecutiveDashboard } from '@/api/dashboard';
import { useApiClient } from '@/hooks/useApiClient';
import { cn } from '@/lib/cn';
import { CARD } from '@/lib/tokens';

/**
 * ExecutiveDashboardPage - route `/dashboard/executive` (H4.7, dashboard eksekutif).
 *
 * Data NYATA `GET /api/v1/dashboard/executive/` (`api/dashboard.ts` ->
 * MODE.executiveDashboard=real). Backend hanya **mengorkestrasi** helper internal
 * H4.1-H4.6 (angka tidak dihitung ulang di UI / Aturan Mutlak #5):
 *
 *   * filter server: `?period=YYYY-MM` (default bulan berjalan) - **hanya** periode,
 *     tanpa filter per customer/produk (drill-down ke halaman H4.1-H4.6);
 *   * KPI per section: penjualan, pembelian, stok, HPP, laba-rugi, produksi;
 *   * `stock = null` = Odoo tak terbaca (fail-safe PARTIAL: section lain tetap
 *     terisi) -> ditampilkan `n/a`, bukan 0;
 *   * `pnl.opex = null` (`opex_source = 'unavailable'`) -> laba bersih = laba kotor;
 *   * `alerts[]` = peringatan informatif dari backend (stok/opex/produk tanpa
 *     `odoo_id`/baris tanpa HPP);
 *   * Muat Ulang memakai escape hatch `?_nocache=1` (bypass cache 300 dtk);
 *   * Export **AKTIF** (H4.8: `ExportButton` -> `POST /api/v1/export/<report>/` = Excel/PDF); halaman read-only (tanpa mutasi).
 *
 * PARALEL dengan B2 SupervisorDashboardPage (`/dashboard/summary/` tidak diubah).
 * Guard route: `SUPERVISOR_ROLES` (supervisor/admin/owner - sama seperti `/dashboard`).
 */

function formatIDR(value: number): string {
  return `Rp${value.toLocaleString('id-ID', { maximumFractionDigits: 0 })}`;
}

function formatQty(value: number): string {
  return value.toLocaleString('id-ID', { maximumFractionDigits: 2 });
}

function formatPct(value: number): string {
  return `${value.toLocaleString('id-ID', { maximumFractionDigits: 2 })}%`;
}

/** `null` (sumber belum tersedia / Odoo tak terbaca) ditampilkan apa adanya - bukan 0. */
function formatOpex(value: number | null): string {
  return value === null ? 'n/a' : formatIDR(value);
}

function formatStockQty(value: number | null): string {
  return value === null ? 'n/a' : `${formatQty(value)} pcs`;
}

export function ExecutiveDashboardPage() {
  const client = useApiClient();

  const [period, setPeriod] = useState('');
  /** Naik +1 setiap Muat Ulang -> `?_nocache=1` dipakai sekali (force refresh). */
  const [forceRefresh, setForceRefresh] = useState(0);

  const dashboard = useQuery({
    queryKey: ['dashboard-executive', period, forceRefresh],
    queryFn: () =>
      fetchExecutiveDashboard(client, {
        period: period === '' ? null : period,
        nocache: forceRefresh > 0,
      }),
    staleTime: 60_000,
  });

  const data = dashboard.data;
  const alerts = data?.alerts ?? [];
  const stock = data?.stock ?? null;
  const opexUnavailable = data !== undefined && data.pnl.opex_source === 'unavailable';
  const queryError =
    dashboard.error === null || dashboard.error === undefined ? null : dashboard.error;
  const loadError =
    queryError === null ? null : 'Gagal memuat dashboard eksekutif (perlu login?).';

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title="Dashboard Eksekutif"
        subtitle="Satu periode, semua KPI: penjualan, pembelian, stok, HPP, laba-rugi, produksi - DB MES, read-only"
        breadcrumb={[{ label: 'Dashboard' }, { label: 'Eksekutif' }]}
      />

      <section className={cn(CARD, 'flex flex-wrap items-end justify-between gap-3')}>
        <div className="flex flex-wrap items-end gap-3">
          <Input
            type="month"
            label="Periode (bulan berjalan default)"
            value={period}
            className="w-40"
            onChange={(event) => {
              setPeriod(event.target.value);
            }}
          />
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <ExportButton
            report="executive"
            filters={{
              period: period === '' ? null : period,
            }}
          />
          <Button
            variant="secondary"
            size="sm"
            icon={RefreshCw}
            loading={dashboard.isFetching}
            onClick={() => {
              setForceRefresh((value) => value + 1);
            }}
          >
            Muat Ulang
          </Button>
        </div>
      </section>

      {loadError === null ? null : (
        <p role="alert" className="text-sm font-medium text-accent-coral">
          {loadError}
        </p>
      )}
      {alerts.length === 0 ? null : (
        <section className={cn(CARD, 'border border-accent-coral/30')} aria-label="Peringatan">
          <div className="flex items-start gap-3">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent-coral/10 text-accent-coral">
              <AlertTriangle className="h-4 w-4" aria-hidden="true" />
            </div>
            <div className="flex flex-col gap-1">
              <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground/80">
                {`Peringatan (${alerts.length})`}
              </span>
              <ul className="flex flex-col gap-1 text-sm text-foreground">
                {alerts.map((alert) => (
                  <li key={alert}>{alert}</li>
                ))}
              </ul>
            </div>
          </div>
        </section>
      )}

      <section className="flex flex-col gap-2">
        <h2 className="text-sm font-semibold text-foreground">Penjualan</h2>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-4">
          <KpiCard
            label="Omzet"
            value={formatIDR(data?.sales.total_amount ?? 0)}
            trend={`${formatQty(data?.sales.count_lines ?? 0)} baris order (accrual)`}
            tone="blue"
            icon={TrendingUp}
          />
          <KpiCard
            label="Order"
            value={formatQty(data?.sales.count_orders ?? 0)}
            trend="order non-CANCELLED dalam periode"
            tone="muted"
            icon={Layers}
          />
          <KpiCard
            label="Belanja"
            value={formatIDR(data?.purchases.total_amount ?? 0)}
            trend={`${formatQty(data?.purchases.count_purchases ?? 0)} PO / ${formatQty(
              data?.purchases.count_lines ?? 0,
            )} baris`}
            tone="coral"
            icon={ShoppingCart}
          />
          <KpiCard
            label="Stok Tercatat"
            value={formatStockQty(stock?.total_qty ?? null)}
            trend={
              stock === null
                ? 'stok tidak terbaca dari Odoo'
                : `${formatQty(stock.product_count)} produk / ${formatQty(
                    stock.location_count,
                  )} lokasi`
            }
            tone={stock === null ? 'coral' : 'blue'}
            icon={Package}
          />
          <KpiCard
            label="Produk Tanpa odoo_id"
            value={formatQty(stock?.unmapped_product_count ?? 0)}
            trend="produk Odoo belum punya master MES"
            tone={(stock?.unmapped_product_count ?? 0) > 0 ? 'coral' : 'muted'}
            icon={AlertTriangle}
          />
        </div>
      </section>
      <section className="flex flex-col gap-2">
        <h2 className="text-sm font-semibold text-foreground">HPP & Laba-Rugi</h2>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-4">
          <KpiCard
            label="HPP (COGS)"
            value={formatIDR(data?.cogs.total_cogs ?? 0)}
            trend={`${formatQty(data?.cogs.rows_with_missing_cost ?? 0)} baris tanpa cost_price`}
            tone="coral"
            icon={Wallet}
          />
          <KpiCard
            label="Laba Kotor"
            value={formatIDR(data?.cogs.gross_profit ?? 0)}
            trend={`margin ${formatPct(data?.cogs.gross_margin_pct ?? 0)}`}
            tone="blue"
            icon={TrendingUp}
          />
          <KpiCard
            label="Opex (Jurnal)"
            value={formatOpex(data?.pnl.opex ?? null)}
            trend={opexUnavailable ? 'opex belum tersedia' : 'jurnal expense H3.4'}
            tone="muted"
            icon={Layers}
          />
          <KpiCard
            label="Laba Bersih"
            value={formatIDR(data?.pnl.net_profit ?? 0)}
            trend={`margin ${formatPct(data?.pnl.net_margin_pct ?? 0)}`}
            tone="blue"
            icon={TrendingDown}
          />
        </div>
      </section>

      <section className="flex flex-col gap-2">
        <h2 className="text-sm font-semibold text-foreground">Produksi</h2>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-4">
          <KpiCard
            label="Output"
            value={`${formatQty(data?.production.output_pcs ?? 0)} pcs`}
            trend={`${formatQty(data?.production.total_bundles ?? 0)} bundle / ${formatQty(
              data?.production.total_work_orders ?? 0,
            )} WO`}
            tone="blue"
            icon={Layers}
          />
          <KpiCard
            label="Scrap"
            value={formatPct(data?.production.scrap_pct ?? 0)}
            trend={`${formatQty(data?.production.scrap_pcs ?? 0)} pcs dari (output + scrap)`}
            tone="coral"
            icon={TrendingDown}
          />
          <KpiCard
            label="Efisiensi Rata-rata"
            value={formatPct(data?.production.avg_efficiency_pct ?? 0)}
            trend="rumus B13 (target per hari per WC)"
            tone="blue"
            icon={TrendingUp}
          />
          <KpiCard
            label="OTD (order-level)"
            value={formatPct(data?.production.otd_pct ?? 0)}
            trend="WO selesai vs deadline order"
            tone="muted"
            icon={Wallet}
          />
        </div>
      </section>

      {opexUnavailable ? (
        <p className="text-xs text-muted-foreground">
          {`Perhatian: chart of accounts expense belum di-pull - opex ditampilkan n/a dan laba bersih = laba kotor (angka tidak dikarang).`}
        </p>
      ) : null}

      <p className="text-xs text-muted-foreground">
        {data === undefined
          ? 'Memuat periode dashboard...'
          : `Periode ${data.period.from} s/d ${data.period.to} - ${alerts.length} peringatan - sumber angka: helper internal H4.1-H4.6 (rumus tidak diduplikasi)`}
        {data?.cached === true ? ' - dari cache backend (5 menit)' : ''}
      </p>


    </div>
  );
}
