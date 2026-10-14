import { useQuery } from '@tanstack/react-query';
import { RefreshCw } from 'lucide-react';
import { Button } from '@/components/atoms/Button';
import { Card } from '@/components/atoms/Card';
import { Spinner } from '@/components/atoms/Spinner';
import { PageHeader } from '@/components/molecules/PageHeader';
import { StatusChip } from '@/components/molecules/StatusChip';
import { fetchAQLSummaries, type AqlRow, type AqlSeverity } from '@/api/qc';
import { useApiClient } from '@/hooks/useApiClient';
import { cn } from '@/lib/cn';
import { TABLE_CELL, TABLE_HEAD } from '@/lib/tokens';
import type { StatusChipStatus } from '@/lib/state-display';

/**
 * AQLDashboardPage - dashboard AQL (REAL `GET /api/v1/quality/aql/`, B5 / F3A.CLOSE).
 *
 * Severity dari backend: `pass` (<=1.5%) · `warn` (<=4.0%) · `fail` (>4.0%).
 * `sample_qty` = jumlah bundle selesai (event BUNDLE_FINISH) pada periode;
 * `defect_qty` = Σ qty defect (event scrap) pada periode.
 */

const EMPTY_ROWS: AqlRow[] = [];

const SEVERITY_CHIP: Record<AqlSeverity, StatusChipStatus> = {
  pass: 'on_track',
  warn: 'delay',
  fail: 'bottleneck',
};

const SEVERITY_LABEL: Record<AqlSeverity, string> = {
  pass: 'Lolos',
  warn: 'Perhatian',
  fail: 'Gagal AQL',
};

export function AQLDashboardPage() {
  const client = useApiClient();

  const { data, isLoading, isFetching, error, refetch } = useQuery({
    queryKey: ['qc-aql'],
    queryFn: () => fetchAQLSummaries(client),
    staleTime: 15_000,
  });

  const rows: AqlRow[] = data?.rows ?? EMPTY_ROWS;

  const totals = rows.reduce(
    (acc, row) => ({
      sample: acc.sample + row.sample_qty,
      defect: acc.defect + row.defect_qty,
    }),
    { sample: 0, defect: 0 },
  );

  const overallPercent =
    totals.sample === 0 ? 0 : Number(((totals.defect / totals.sample) * 100).toFixed(2));
  const maxPercent = rows.reduce((max, row) => (row.aql_pct > max ? row.aql_pct : max), 0);

  const kpis = [
    { id: 'sample', label: 'Total Sampel', value: `${totals.sample} bundle` },
    { id: 'defect', label: 'Total Defect', value: `${totals.defect} pcs` },
    { id: 'aql', label: 'AQL Keseluruhan', value: `${overallPercent}%` },
  ];

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title="AQL Dashboard"
        subtitle="Acceptable Quality Level per work center"
        breadcrumb={[{ label: 'Quality' }, { label: 'AQL' }]}
        actions={
          <Button
            variant="secondary"
            size="sm"
            icon={RefreshCw}
            loading={isFetching}
            onClick={() => {
              void refetch();
            }}
          >
            Refresh
          </Button>
        }
      />

      {isLoading ? (
        <div className="flex items-center justify-center p-8">
          <Spinner size="lg" />
        </div>
      ) : null}

      {error !== null ? (
        <p role="alert" className="text-sm font-medium text-accent-coral">
          Gagal memuat data AQL.
        </p>
      ) : null}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        {kpis.map((kpi) => (
          <Card key={kpi.id} as="article" className="flex flex-col gap-1">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground/80">
              {kpi.label}
            </p>
            <p className="text-2xl font-bold tabular-nums tracking-tight text-foreground">
              {kpi.value}
            </p>
          </Card>
        ))}
      </div>

      <Card as="section" className="flex flex-col gap-4">
        <h2 className="text-sm font-semibold tracking-tight text-foreground">
          AQL per Work Center
        </h2>

        {rows.length === 0 && !isLoading ? (
          <p className="text-sm text-muted-foreground">Belum ada data AQL pada periode ini.</p>
        ) : null}

        {rows.length > 0 ? (
          <>
            <ul className="flex flex-col gap-3">
              {rows.map((row) => {
                const width = maxPercent === 0 ? 0 : Math.round((row.aql_pct / maxPercent) * 100);

                return (
                  <li key={row.wc_code} className="flex flex-col gap-1">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-sm font-medium text-foreground">{row.wc_name}</span>
                      <span className="text-xs tabular-nums text-muted-foreground">
                        {row.aql_pct}% - {row.defect_qty} defect / {row.sample_qty} sampel
                      </span>
                    </div>
                    <div className="h-2 w-full overflow-hidden rounded-pill bg-muted">
                      <div
                        className={cn(
                          'h-full rounded-pill',
                          row.severity === 'fail' ? 'bg-accent-coral' : 'bg-accent-blue',
                        )}
                        style={{ width: `${width}%` }}
                      />
                    </div>
                  </li>
                );
              })}
            </ul>

            <div className="overflow-x-auto">
              <table className="w-full border-collapse">
                <caption className="sr-only">Ringkasan AQL per work center</caption>
                <thead>
                  <tr>
                    <th scope="col" className={TABLE_HEAD}>
                      Work Center
                    </th>
                    <th scope="col" className={TABLE_HEAD}>
                      Sampel
                    </th>
                    <th scope="col" className={TABLE_HEAD}>
                      Defect
                    </th>
                    <th scope="col" className={TABLE_HEAD}>
                      AQL %
                    </th>
                    <th scope="col" className={TABLE_HEAD}>
                      Status
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={row.wc_code}>
                      <td className={TABLE_CELL}>
                        {row.wc_name}{' '}
                        <span className="font-mono text-xs text-muted-foreground">
                          ({row.wc_code})
                        </span>
                      </td>
                      <td className={TABLE_CELL}>{row.sample_qty}</td>
                      <td className={TABLE_CELL}>{row.defect_qty}</td>
                      <td className={TABLE_CELL}>{row.aql_pct}</td>
                      <td className={TABLE_CELL}>
                        <StatusChip
                          status={SEVERITY_CHIP[row.severity]}
                          label={SEVERITY_LABEL[row.severity]}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        ) : null}
      </Card>
    </div>
  );
}
