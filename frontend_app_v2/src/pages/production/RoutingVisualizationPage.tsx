import { useCallback, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { RefreshCw, Waypoints } from 'lucide-react';
import { Button } from '@/components/atoms/Button';
import { Spinner } from '@/components/atoms/Spinner';
import { PageHeader } from '@/components/molecules/PageHeader';
import { RoutingGraph } from '@/components/molecules/RoutingGraph';
import { fetchRoutingGraph } from '@/api/routing';
import { useRole } from '@/app/useRole';
import { useApiClient } from '@/hooks/useApiClient';
import { cn } from '@/lib/cn';
import { CARD } from '@/lib/tokens';
// Tipe DAG diimpor sebagai NAMESPACE: nama `RoutingGraph` tetap milik komponen
// (dua import bernama sama = duplicate identifier), dan tidak perlu alias impor.
import type * as routingTypes from '@/types/routing';

/**
 * RoutingVisualizationPage - route `/production/routing` (supervisor/admin/owner).
 *
 * READ-ONLY untuk supervisor: `onDrag` sengaja TIDAK diberikan ke `RoutingGraph`
 * (molecule hanya mengaktifkan drag kalau `onDrag !== undefined`), jadi node tidak
 * bisa digeser. Admin mendapat `onDrag` + state lokal supaya bisa menggeser node
 * (editor ringan - penyimpanan konfigurasi DAG menyusul di fase Settings).
 *
 * Klik node = highlight saja (tanpa navigasi).
 */

export function RoutingVisualizationPage() {
  const role = useRole();
  const canDrag = role === 'admin';
  const client = useApiClient();

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['routing-graph'],
    queryFn: () => fetchRoutingGraph(client),
    staleTime: 30_000,
  });

  const [graph, setGraph] = useState<routingTypes.RoutingGraph | null>(null);
  const [selectedId, setSelectedId] = useState<string | undefined>(undefined);

  const activeGraph = graph ?? data ?? null;

  const handleDrag = useCallback((id: string, pos: { x: number; y: number }): void => {
    setGraph((previous) => {
      const source = previous ?? data;
      if (source === undefined) return previous;

      return {
        nodes: source.nodes.map((node) =>
          node.id === id ? { ...node, position: pos } : node,
        ),
        edges: source.edges,
      };
    });
  }, [data]);

  if (isLoading) {
    return (
      <div className="flex min-h-full items-center justify-center p-8">
        <Spinner size="lg" />
      </div>
    );
  }

  if (error !== null || activeGraph === null) {
    return (
      <div className="flex min-h-full flex-col items-center justify-center gap-4 p-8">
        <p role="alert" className="text-sm font-semibold text-foreground">
          Gagal memuat DAG routing.
        </p>
        <Button
          variant="secondary"
          onClick={() => {
            void refetch();
          }}
        >
          Coba Lagi
        </Button>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title="Routing Visualization"
        subtitle="Alur produksi antar work center"
        breadcrumb={[{ label: 'Production' }, { label: 'Routing' }]}
        actions={
          <>
            <span className="self-center text-xs text-muted-foreground">
              {canDrag ? 'Mode admin: node bisa digeser' : 'Mode baca (read-only)'}
            </span>
            <Button
              variant="secondary"
              size="sm"
              icon={RefreshCw}
              onClick={() => {
                setGraph(null);
                setSelectedId(undefined);
                void refetch();
              }}
            >
              Reset &amp; Refresh
            </Button>
          </>
        }
      />

      <section className="relative flex min-h-[420px] flex-1 flex-col gap-3 overflow-hidden rounded-card border border-border/40 bg-card p-4">
        <div className="flex flex-wrap items-center gap-3">
          <span className="flex items-center gap-2 text-xs text-muted-foreground">
            <span aria-hidden="true" className="h-0.5 w-6 rounded-pill bg-accent-coral" />
            Rework loop (putus-putus)
          </span>

          <span className="ml-auto flex items-center gap-1.5 text-xs text-muted-foreground">
            <Waypoints className="h-3.5 w-3.5" aria-hidden="true" />
            {activeGraph.nodes.length} node - {activeGraph.edges.length} edge
          </span>
        </div>

        <RoutingGraph
          graph={activeGraph}
          selectedId={selectedId}
          onSelect={setSelectedId}
          onDrag={canDrag ? handleDrag : undefined}
        />
      </section>

      {selectedId !== undefined ? (
        <p className="text-xs text-muted-foreground">
          Node terpilih: <span className="font-mono text-foreground">{selectedId}</span>
        </p>
      ) : null}

      <p className={cn(CARD, 'text-xs text-muted-foreground')}>
        DAG dari backend `GET /api/v1/routing/graph/` (F2c.1) - node menampilkan
        id/label/step_no; edge rework digambar putus-putus. Editor konfigurasi DAG penuh
        ada di halaman Settings (masih dummy).
      </p>
    </div>
  );
}
