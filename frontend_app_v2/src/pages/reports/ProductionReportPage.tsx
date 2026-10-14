import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Layers, RefreshCw, TrendingDown, TrendingUp, Wallet, FileText } from 'lucide-react';
import { Button } from '@/components/atoms/Button';
import { Input } from '@/components/atoms/Input';
import { Select, type SelectOption } from '@/components/atoms/Select';
import { DenseTable, type DenseTableColumn } from '@/components/molecules/DenseTable';
import { ExportButton } from '@/components/molecules/ExportButton';
import { KpiCard } from '@/components/molecules/KpiCard';
import { PageHeader } from '@/components/molecules/PageHeader';
import {
  fetchProductionReport,
  PRODUCTION_GROUP_BY_VALUES,
  type ProductionGroupBy,
  type ProductionReportRow,
} from '@/api/reports';
import { fetchWorkCenters } from '@/api/masterWorkCenters';
import { fetchProductionLines } from '@/api/masterProductionLines';
import { useApiClient } from '@/hooks/useApiClient';
import { cn } from '@/lib/cn';
import { CARD } from '@/lib/tokens';

/**
 * ProductionReportPage - route `/reports/production` (H4.6, laporan produksi).
 *
 * Data NYATA `GET /api/v1/reports/production/` (`api/reports.ts` -> MODE.reportProduction=real):
 *
 *   * SUPERSET B13/B16/B18-B21: menambah dimensi periode (endpoint lama tidak diubah);
 *   * filter server: `?period=YYYY-MM` (default bulan berjalan), `?group_by=period|work_center|line`,
 *     `?work_center_id=`/`?line_id=` (pk MES);
 *   * basis waktu per metrik (`filters.basis`): output/efisiensi/OTD = `BundleEvent.ts`,
 *     scrap = `ScrapAccumulator.created_at`;
 *   * KPI: output, scrap (+%), rework/end-loss (terpisah), efisiensi rata-rata, OTD, bundle/WO;
 *   * tabel memakai `DenseTable` (bukan tabel paralel);
 *   * Muat Ulang memakai escape hatch `?_nocache=1` (bypass cache 300 dtk);
 *   * tombol Export **AKTIF** (H4.8: `ExportButton` -> `POST /api/v1/export/<report>/` = Excel/PDF); halaman read-only (tanpa mutasi).
 */

const GROUP_BY_LABEL: Record<ProductionGroupBy, string> = {
  period: 'Bulan',
  work_center: 'Work Center',
  line: 'Line',
};

const GROUP_BY_OPTIONS: SelectOption[] = PRODUCTION_GROUP_BY_VALUES.map((value) => ({
  value,
  label: GROUP_BY_LABEL[value],
}));

/** Semua opsi dropdown keluar dari master MES (tanpa data karangan). */
const ALL_WORK_CENTERS: SelectOption = { value: '', label: 'Semua work center' };
const ALL_LINES: SelectOption = { value: '', label: 'Semua line' };

function formatQty(value: number): string {
  return value.toLocaleString('id-ID', { maximumFractionDigits: 2 });
}

function formatPct(value: number): string {
  return `${value.toLocaleString('id-ID', { maximumFractionDigits: 2 })}%`;
}

/** `otd_pct = null` (baris work center/line) ditampilkan apa adanya - bukan 0. */
function formatOtd(value: number | null): string {
  return value === null ? '-' : formatPct(value);
}

const COLUMNS: DenseTableColumn<ProductionReportRow>[] = [
  {
    key: 'label',
    label: 'Periode / Grup',
    render: (row) => (
      <span>
        <span className="font-medium text-foreground">{row.label}</span>
        {row.key === '' ? null : (
          <span className="ml-2 font-mono text-xs text-muted-foreground">{row.key}</span>
        )}
      </span>
    ),
  },
  {
    key: 'output_pcs',
    label: 'Output (pcs)',
    align: 'right',
    render: (row) => <span className="font-mono tabular-nums">{formatQty(row.output_pcs)}</span>,
  },
  {
    key: 'scrap_pcs',
    label: 'Scrap (pcs)',
    align: 'right',
    render: (row) => <span className="font-mono tabular-nums">{formatQty(row.scrap_pcs)}</span>,
  },
  {
    key: 'scrap_pct',
    label: 'Scrap %',
    align: 'right',
    render: (row) => <span className="font-mono tabular-nums">{formatPct(row.scrap_pct)}</span>,
  },
  {
    key: 'efficiency_pct',
    label: 'Efisiensi %',
    align: 'right',
    render: (row) => (
      <span className="font-mono tabular-nums">{formatPct(row.efficiency_pct)}</span>
    ),
  },
  {
    key: 'otd_pct',
    label: 'OTD (order-level)',
    align: 'right',
    render: (row) => <span className="font-mono tabular-nums">{formatOtd(row.otd_pct)}</span>,
  },
  {
    key: 'bundle_count',
    label: 'Bundle',
    align: 'right',
    render: (row) => formatQty(row.bundle_count ?? 0),
  },
];

export function ProductionReportPage() {
  const client = useApiClient();

  const [period, setPeriod] = useState('');
  const [groupBy, setGroupBy] = useState<ProductionGroupBy>('period');
  const [workCenterId, setWorkCenterId] = useState('');
  const [lineId, setLineId] = useState('');
  /** Naik +1 setiap Muat Ulang -> `?_nocache=1` dipakai sekali (force refresh). */
  const [forceRefresh, setForceRefresh] = useState(0);

  const workCenters = useQuery({
    queryKey: ['reports-production-work-centers'],
    queryFn: () => fetchWorkCenters(client, { limit: 200, active: true }),
    staleTime: 300_000,
  });

  const lines = useQuery({
    queryKey: ['reports-production-lines'],
    queryFn: () => fetchProductionLines(client, { limit: 200, active: true }),
    staleTime: 300_000,
  });

  const report = useQuery({
    queryKey: ['reports-production', period, groupBy, workCenterId, lineId, forceRefresh],
    queryFn: () =>
      fetchProductionReport(client, {
        period: period === '' ? null : period,
        groupBy,
        workCenterId: workCenterId === '' ? null : Number(workCenterId),
        lineId: lineId === '' ? null : Number(lineId),
        nocache: forceRefresh > 0,
      }),
    staleTime: 60_000,
  });

  const workCenterOptions: SelectOption[] = [
    ALL_WORK_CENTERS,
    ...(workCenters.data?.rows ?? []).map((row) => ({
      value: String(row.id),
      label: `${row.code} - ${row.name}`,
    })),
  ];

  const lineOptions: SelectOption[] = [
    ALL_LINES,
    ...(lines.data?.rows ?? []).map((row) => ({
      value: String(row.id),
      label: `${row.code} - ${row.name}`,
    })),
  ];

  const rows = report.data?.rows ?? [];
  const summary = report.data?.summary;
  const basis = report.data?.filters.basis;
  const queryError = report.error === null || report.error === undefined ? null : report.error;
  const loadError = queryError === null ? null : 'Gagal memuat laporan produksi (perlu login?).';


  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title="Laporan Produksi"
        subtitle="Output, scrap, efisiensi, dan OTD per periode / work center / line - DB MES, read-only"
        breadcrumb={[{ label: 'Reports' }, { label: 'Produksi' }]}
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
              setGroupBy(event.target.value as ProductionGroupBy);
            }}
          />
          <Select
            label="Work center"
            options={workCenterOptions}
            value={workCenterId}
            className="w-56"
            onChange={(event) => {
              setWorkCenterId(event.target.value);
            }}
          />
          <Select
            label="Line"
            options={lineOptions}
            value={lineId}
            className="w-56"
            onChange={(event) => {
              setLineId(event.target.value);
            }}
          />
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <ExportButton
            report="production"
            filters={{
              period: period === '' ? null : period,
              groupBy,
              workCenterId: workCenterId === '' ? null : Number(workCenterId),
              lineId: lineId === '' ? null : Number(lineId),
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
          label="Output"
          value={`${formatQty(summary?.total_output_pcs ?? 0)} pcs`}
          trend={`${formatQty(summary?.total_bundles ?? 0)} bundle / ${formatQty(
            summary?.total_work_orders ?? 0,
          )} WO`}
          tone="blue"
          icon={Layers}
        />
        <KpiCard
          label="Scrap"
          value={`${formatQty(summary?.total_scrap_pcs ?? 0)} pcs`}
          trend={`${formatPct(summary?.scrap_pct ?? 0)} dari (output + scrap)`}
          tone="coral"
          icon={TrendingDown}
        />
        <KpiCard
          label="Rework / End-Loss"
          value={`${formatQty(summary?.total_rework_pcs ?? 0)} / ${formatQty(
            summary?.total_end_loss_pcs ?? 0,
          )} pcs`}
          trend="terpisah dari scrap (konsep berbeda)"
          tone="muted"
          icon={FileText}
        />
        <KpiCard
          label="Efisiensi Rata-rata"
          value={formatPct(summary?.avg_efficiency_pct ?? 0)}
          trend="rumus B13 (target per hari per WC)"
          tone="blue"
          icon={TrendingUp}
        />
        <KpiCard
          label="OTD (order-level)"
          value={formatPct(summary?.otd_pct ?? 0)}
          trend="WO selesai vs deadline order"
          tone="coral"
          icon={Wallet}
        />
        <KpiCard
          label="Cakupan"
          value={`${formatQty(summary?.total_output_pcs ?? 0)} pcs`}
          trend={`per ${GROUP_BY_LABEL[report.data?.group_by ?? groupBy]}`}
          tone="muted"
          icon={Layers}
        />
      </section>

      <section className={cn(CARD, 'p-0')}>
        <DenseTable
          columns={COLUMNS}
          rows={rows}
          loading={report.isLoading}
          error={loadError}
          onRetry={() => {
            void report.refetch();
          }}
          emptyMessage="Tidak ada aktivitas produksi pada filter ini."
        />
      </section>

      <p className="text-xs text-muted-foreground">
        {report.data === undefined
          ? 'Memuat rentang laporan...'
          : `Rentang ${report.data.period.from} s/d ${report.data.period.to} - basis output ${basis?.output ?? '-'} · scrap ${basis?.scrap ?? '-'}`}
        {report.data?.cached === true ? ' - dari cache backend (5 menit)' : ''}
      </p>
    </div>
  );
}
