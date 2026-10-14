import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { FileText, Layers, RefreshCw, TrendingDown, TrendingUp, Wallet } from 'lucide-react';
import { Button } from '@/components/atoms/Button';
import { Input } from '@/components/atoms/Input';
import { Select, type SelectOption } from '@/components/atoms/Select';
import { DenseTable, type DenseTableColumn } from '@/components/molecules/DenseTable';
import { ExportButton } from '@/components/molecules/ExportButton';
import { KpiCard } from '@/components/molecules/KpiCard';
import { PageHeader } from '@/components/molecules/PageHeader';
import {
  fetchPnlReport,
  PNL_GROUP_BY_VALUES,
  type PnlGroupBy,
  type PnlReportRow,
} from '@/api/reports';
import { useApiClient } from '@/hooks/useApiClient';
import { cn } from '@/lib/cn';
import { CARD } from '@/lib/tokens';

/**
 * PnlReportPage - route `/reports/pnl` (H4.5, laporan laba-rugi / PnL).
 *
 * Data NYATA `GET /api/v1/reports/pnl/` (`api/reports.ts` -> MODE.reportPnl=real):
 *
 *   * rantai: revenue (qty x price_unit) - HPP simplified (qty x cost_price) =
 *     laba kotor; dikurangi opex (jurnal expense H3.4) = laba bersih;
 *   * filter server: `?period=YYYY-MM` (default bulan berjalan), `?group_by=period|quarter`;
 *   * KPI: revenue, HPP, laba kotor, margin kotor, opex, laba bersih, margin bersih;
 *   * peringatan `opex_source = unavailable` (chart of accounts expense belum ada ->
 *     laba bersih = laba kotor, angka tidak dikarang) + `rows_with_missing_cost`;
 *   * tabel memakai `DenseTable` (bukan tabel paralel);
 *   * Muat Ulang memakai escape hatch `?_nocache=1` (bypass cache 300 dtk);
 *   * tombol Export **AKTIF** (H4.8: `ExportButton` -> `POST /api/v1/export/<report>/` = Excel/PDF); halaman read-only (tanpa mutasi).
 *
 * Read-only: tidak pernah mengirim mutasi (tanpa POST/PUT/DELETE) dan tidak menyentuh
 * jurnal H3.4. Guard route: `REPORTS_ROLES` (supervisor/admin/owner).
 */

const GROUP_BY_LABEL: Record<PnlGroupBy, string> = {
  period: 'Bulan',
  quarter: 'Kuartal',
};

const GROUP_BY_OPTIONS: SelectOption[] = PNL_GROUP_BY_VALUES.map((value) => ({
  value,
  label: GROUP_BY_LABEL[value],
}));

function formatIDR(value: number): string {
  return `Rp${value.toLocaleString('id-ID', { maximumFractionDigits: 0 })}`;
}

function formatQty(value: number): string {
  return value.toLocaleString('id-ID');
}

function formatPct(value: number): string {
  return `${value.toLocaleString('id-ID', { maximumFractionDigits: 2 })}%`;
}

/** `opex = null` (sumber belum tersedia) ditampilkan apa adanya - bukan 0. */
function formatOpex(value: number | null): string {
  return value === null ? 'n/a' : formatIDR(value);
}

const COLUMNS: DenseTableColumn<PnlReportRow>[] = [
  {
    key: 'label',
    label: 'Periode',
    render: (row) => (
      <span>
        <span className="font-medium text-foreground">{row.label}</span>
        {row.key === '' ? null : (
          <span className="ml-2 font-mono text-xs text-muted-foreground">{row.key}</span>
        )}
        {row.has_missing_cost ? (
          <span className="ml-2 text-xs text-muted-foreground">
            {row.missing_cost_reason === 'no_product' ? '(produk belum sinkron)' : '(HPP belum diisi)'}
          </span>
        ) : null}
      </span>
    ),
  },
  {
    key: 'revenue',
    label: 'Revenue (IDR)',
    align: 'right',
    render: (row) => <span className="font-mono tabular-nums">{formatIDR(row.revenue)}</span>,
  },
  {
    key: 'cogs',
    label: 'HPP (IDR)',
    align: 'right',
    render: (row) => <span className="font-mono tabular-nums">{formatIDR(row.cogs)}</span>,
  },
  {
    key: 'gross_profit',
    label: 'Laba Kotor',
    align: 'right',
    render: (row) => <span className="font-mono tabular-nums">{formatIDR(row.gross_profit)}</span>,
  },
  {
    key: 'opex',
    label: 'Opex',
    align: 'right',
    render: (row) => <span className="font-mono tabular-nums">{formatOpex(row.opex)}</span>,
  },
  {
    key: 'net_profit',
    label: 'Laba Bersih',
    align: 'right',
    render: (row) => <span className="font-mono tabular-nums">{formatIDR(row.net_profit)}</span>,
  },
  {
    key: 'net_margin_pct',
    label: 'Margin',
    align: 'right',
    render: (row) => <span className="font-mono tabular-nums">{formatPct(row.net_margin_pct)}</span>,
  },
];

export function PnlReportPage() {
  const client = useApiClient();

  const [period, setPeriod] = useState('');
  const [groupBy, setGroupBy] = useState<PnlGroupBy>('period');
  /** Naik +1 setiap Muat Ulang -> `?_nocache=1` dipakai sekali (force refresh). */
  const [forceRefresh, setForceRefresh] = useState(0);

  const report = useQuery({
    queryKey: ['reports-pnl', period, groupBy, forceRefresh],
    queryFn: () =>
      fetchPnlReport(client, {
        period: period === '' ? null : period,
        groupBy,
        nocache: forceRefresh > 0,
      }),
    staleTime: 60_000,
  });

  const rows = report.data?.rows ?? [];
  const summary = report.data?.summary;
  // opex_source 'unavailable' -> laba bersih = laba kotor (angka tidak dikarang).
  const opexUnavailable = summary !== undefined && summary.opex_source === 'unavailable';
  const queryError = report.error === null || report.error === undefined ? null : report.error;
  const loadError = queryError === null ? null : 'Gagal memuat laporan laba-rugi (perlu login?).';


  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title="Laporan Laba-Rugi"
        subtitle="Revenue - HPP (simplified) - biaya operasional (jurnal) = laba bersih - DB MES, read-only"
        breadcrumb={[{ label: 'Reports' }, { label: 'Laba-Rugi' }]}
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
          <Select
            label="Kelompokkan"
            options={GROUP_BY_OPTIONS}
            value={groupBy}
            className="w-40"
            onChange={(event) => {
              setGroupBy(event.target.value as PnlGroupBy);
            }}
          />
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <ExportButton
            report="pnl"
            filters={{
              period: period === '' ? null : period,
              groupBy,
            }}
          />
          <Button
            variant="secondary"
            size="sm"
            icon={RefreshCw}
            loading={report.isFetching}
            onClick={() => {
              setForceRefresh((value) => value + 1);
            }}
          >
            Muat Ulang
          </Button>
        </div>
      </section>

      <section className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-4">
        <KpiCard
          label="Revenue"
          value={formatIDR(summary?.revenue ?? 0)}
          trend={`${formatQty(summary?.order_count ?? 0)} order / ${formatQty(
            summary?.line_count ?? 0,
          )} baris`}
          tone="blue"
          icon={TrendingUp}
        />
        <KpiCard
          label="HPP (Simplified)"
          value={formatIDR(summary?.cogs ?? 0)}
          trend="qty x cost_price (tanpa tenaga kerja/overhead)"
          tone="muted"
          icon={FileText}
        />
        <KpiCard
          label="Laba Kotor"
          value={formatIDR(summary?.gross_profit ?? 0)}
          trend="revenue dikurangi HPP"
          tone="coral"
          icon={Wallet}
        />
        <KpiCard
          label="Margin Kotor"
          value={formatPct(summary?.gross_margin_pct ?? 0)}
          trend={`per ${GROUP_BY_LABEL[report.data?.group_by ?? groupBy]}`}
          tone="blue"
          icon={Layers}
        />
        <KpiCard
          label="Opex (Jurnal)"
          value={formatOpex(summary?.opex ?? null)}
          trend={opexUnavailable ? 'opex belum tersedia' : 'CONFIRMED/SENT/DONE'}
          tone="muted"
          icon={FileText}
        />
        <KpiCard
          label="Laba Bersih"
          value={formatIDR(summary?.net_profit ?? 0)}
          trend="laba kotor dikurangi opex"
          tone="blue"
          icon={TrendingDown}
        />
        <KpiCard
          label="Margin Bersih"
          value={formatPct(summary?.net_margin_pct ?? 0)}
          trend={`mata uang ${summary?.currency ?? 'IDR'}`}
          tone="coral"
          icon={Layers}
        />
      </section>

      {opexUnavailable ? (
        <p className="text-xs text-muted-foreground">
          {`Perhatian: sumber biaya operasional belum tersedia (chart of accounts expense belum ada di MES) - opex ditampilkan n/a dan laba bersih = laba kotor. Angka tidak dikarang.`}
        </p>
      ) : null}

      {(summary?.rows_with_missing_cost ?? 0) > 0 ? (
        <p className="text-xs text-muted-foreground">
          {`Perhatian: ${formatQty(summary?.rows_with_missing_cost ?? 0)} baris order belum punya HPP (produk belum tersinkron atau cost_price masih 0) - HPP dihitung 0, laba kotor bisa terlihat lebih tinggi.`}
        </p>
      ) : null}

      <section className={cn(CARD, 'p-0')}>
        <DenseTable
          columns={COLUMNS}
          rows={rows}
          loading={report.isLoading}
          error={loadError}
          onRetry={() => {
            void report.refetch();
          }}
          emptyMessage="Tidak ada data pada filter ini."
        />
      </section>

      <p className="text-xs text-muted-foreground">
        {report.data === undefined
          ? 'Memuat rentang laporan...'
          : `Rentang ${report.data.period.from} s/d ${report.data.period.to}`}
        {report.data?.cached === true ? ' - dari cache backend (5 menit)' : ''}
      </p>
    </div>
  );
}
