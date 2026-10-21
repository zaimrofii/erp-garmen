import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { RefreshCw } from 'lucide-react';
import { Button } from '@/components/atoms/Button';
import { Input } from '@/components/atoms/Input';
import { Spinner } from '@/components/atoms/Spinner';
import { PageHeader } from '@/components/molecules/PageHeader';
import { fetchAIObservability } from '@/api/aiObservability';
import { useApiClient } from '@/hooks/useApiClient';
import { cn } from '@/lib/cn';
import {
  chartPoints,
  defaultRange,
  formatPct,
  formatUsd,
} from '@/lib/ai-observability';
import { BADGE, CARD } from '@/lib/tokens';
import type { AIObservabilityStats } from '@/types/ai-observability';

/**
 * AIObservabilityPage — `/settings/ai-observability` (Sprint F.3, ADMIN/OWNER).
 *
 * Sumber: blueprint §2 (I Observability) + endpoint `/ai/observability/`.
 */
export function AIObservabilityPage({
  initialStats,
}: {
  initialStats?: AIObservabilityStats;
} = {}) {
  const client = useApiClient();
  const initial = useMemo(() => defaultRange(), []);
  const [dateFrom, setDateFrom] = useState(initial.from);
  const [dateTo, setDateTo] = useState(initial.to);
  const [refresh, setRefresh] = useState(0);

  const query = useQuery({
    queryKey: ['ai-observability', dateFrom, dateTo, refresh],
    queryFn: () =>
      fetchAIObservability(client, {
        dateFrom,
        dateTo,
        nocache: refresh > 0,
      }),
    enabled: initialStats === undefined,
    staleTime: 60_000,
  });

  const stats = initialStats ?? query.data;

  if (stats === undefined) {
    return (
      <div className="flex min-h-full flex-col gap-4 p-4 lg:p-6">
        <PageHeader title="AI Observability" subtitle="Token, biaya, latensi, HITL" />
        <div className={cn(CARD, 'flex items-center gap-2 text-sm text-muted-foreground')}>
          <Spinner size="sm" />
          {query.error === null
            ? 'Memuat observability AI...'
            : 'Gagal memuat observability AI.'}
        </div>
      </div>
    );
  }

  const totals = stats.totals;
  const points = chartPoints(stats.by_day.map((row) => row.cost_usd));

  return (
    <div className="flex min-h-full flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title="AI Observability"
        subtitle="Token, biaya, latensi, cache, HITL, dan drift percakapan AI"
        breadcrumb={[{ label: 'Pengaturan' }, { label: 'AI Observability' }]}
        actions={
          <Button
            variant="secondary"
            size="sm"
            icon={RefreshCw}
            onClick={() => {
              setRefresh((value) => value + 1);
            }}
          >
            Muat Ulang
          </Button>
        }
      />

      <section className={cn(CARD, 'grid grid-cols-2 gap-3 lg:grid-cols-4')}>
        <label className="flex flex-col gap-1 text-xs">
          <span className="text-muted-foreground">Dari tanggal</span>
          <Input
            label="Dari tanggal"
            type="date"
            value={dateFrom}
            onChange={(event) => {
              setDateFrom(event.target.value);
            }}
          />
        </label>
        <label className="flex flex-col gap-1 text-xs">
          <span className="text-muted-foreground">Sampai tanggal</span>
          <Input
            label="Sampai tanggal"
            type="date"
            value={dateTo}
            onChange={(event) => {
              setDateTo(event.target.value);
            }}
          />
        </label>
      </section>

      {totals.requests === 0 ? (
        <p className={cn(CARD, 'text-sm text-muted-foreground')}>
          Belum ada data observability. AI belum pernah dipanggil.
        </p>
      ) : (
        <>
          <section className="grid grid-cols-2 gap-3 lg:grid-cols-5">
            <Kpi label="Total request" value={String(totals.requests)} />
            <Kpi label="Total biaya" value={formatUsd(totals.cost_usd)} />
            <Kpi label="Cache hit" value={formatPct(stats.cache_hit_ratio)} />
            <Kpi label="HITL approval" value={formatPct(stats.hitl_approval_rate)} />
            <Kpi
              label="Latensi rata-rata"
              value={`${Math.round(totals.latency_avg_ms)} ms`}
            />
          </section>

          <section className={cn(CARD, 'flex flex-col gap-2')}>
            <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Biaya per hari
            </h2>
            <svg
              role="img"
              aria-label="Grafik biaya per hari"
              viewBox="0 0 320 80"
              className="h-24 w-full text-accent-blue"
            >
              <polyline
                points={points}
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
              />
            </svg>
            <p className="text-[11px] text-muted-foreground">
              {stats.by_day.length} hari · {stats.cached ? 'dari cache backend' : 'data segar'}
            </p>
          </section>

          <section className="grid grid-cols-1 gap-3 lg:grid-cols-2">
            <Table
              title="Tool calls"
              head={['Tool', 'Calls', 'Avg ms']}
              rows={stats.by_tool.map((row) => [
                row.tool,
                String(row.calls),
                String(Math.round(row.avg_duration_ms)),
              ])}
            />
            <Table
              title="Decision gate"
              head={['Gate', 'Jumlah']}
              rows={Object.entries(stats.by_decision_gate).map(([gate, count]) => [
                gate,
                String(count),
              ])}
            />
          </section>

          <section className="grid grid-cols-1 gap-3 lg:grid-cols-2">
            <Table
              title="Top queries (hash)"
              head={['Hash', 'Jumlah']}
              rows={stats.top_queries.map((row) => [row.query_hash, String(row.count)])}
            />
            <div className={cn(CARD, 'flex flex-col gap-1 text-sm')}>
              <span className="text-xs uppercase tracking-wide text-muted-foreground">
                Token
              </span>
              <span>
                Prompt: {totals.tokens_prompt} · Completion: {totals.tokens_completion}
              </span>
              <span className="text-xs text-muted-foreground">
                HITL: {totals.hitl_required} diminta · {totals.hitl_approved} disetujui ·{' '}
                {totals.hitl_rejected} ditolak
              </span>
            </div>
          </section>

        </>
      )}
    </div>
  );
}

function Kpi({ label, value }: { label: string; value: string }) {
  return (
    <div
      className={cn(CARD, 'flex flex-col gap-1 p-3')}
      data-testid="ai-observability-kpi"
    >
      <span className="text-[11px] uppercase tracking-wide text-muted-foreground">
        {label}
      </span>
      <span className="text-lg font-semibold tabular-nums text-foreground">{value}</span>
    </div>
  );
}

function Table({
  title,
  head,
  rows,
}: {
  title: string;
  head: string[];
  rows: string[][];
}) {
  return (
    <section className={cn(CARD, 'flex flex-col gap-2 p-3')}>
      <h2 className={cn(BADGE, 'w-fit bg-muted/60 text-muted-foreground')}>{title}</h2>
      <table className="w-full text-left text-xs">
        <thead>
          <tr className="text-muted-foreground">
            {head.map((label) => (
              <th key={label} className="py-1 font-medium">
                {label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td className="py-1 text-muted-foreground" colSpan={head.length}>
                Tidak ada data.
              </td>
            </tr>
          ) : (
            rows.map((row, index) => (
              <tr
                key={`${title}-${String(index)}`}
                className="border-t border-border/40"
              >
                {row.map((cell, cellIndex) => (
                  <td
                    key={`${title}-${String(cellIndex)}`}
                    className="py-1 tabular-nums text-foreground"
                  >
                    {cell}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </section>
  );
}

