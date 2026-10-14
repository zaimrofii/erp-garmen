import { useCallback, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Plus, RotateCcw, Save, Trash2 } from 'lucide-react';
import { Button } from '@/components/atoms/Button';
import { Input } from '@/components/atoms/Input';
import { Spinner } from '@/components/atoms/Spinner';
import { Toast, type ToastTone } from '@/components/atoms/Toast';
import { FormField } from '@/components/molecules/FormField';
import { PageHeader } from '@/components/molecules/PageHeader';
// Tipe DAG diimpor sebagai NAMESPACE supaya nama komponen `RoutingGraph` (molecules)
// tetap bebas dari tabrakan nama tipe - pola sama dengan RoutingVisualizationPage (Fase 19).
import { RoutingGraph } from '@/components/molecules/RoutingGraph';
import { fetchRoutingConfigs, saveRoutingConfig } from '@/api/settings';
import { useFeedback } from '@/app/app-runtime';
import { useApiClient } from '@/hooks/useApiClient';
import { cn } from '@/lib/cn';
import { CARD, PILL_GHOST, PILL_PRIMARY, PILL_SECONDARY } from '@/lib/tokens';
import type * as routingTypes from '@/types/routing';
import type { RoutingConfig } from '@/types/settings';

/**
 * RoutingConfigPage - route `/settings/routing` (khusus admin). Screen E §3.5.
 *
 * DAG editor 2-panel: kanvas (drag node) + panel properti.
 *   - `RoutingGraph` molecule (Fase 15) TIDAK diubah: node bisa digeser HANYA kalau
 *     `onDrag` diberikan; molecule yang menggambar SVG edge + node-nya sendiri.
 *   - Perubahan lokal disimpan di `draftGraph` (state halaman); "Simpan" mengirim ke
 *     `saveRoutingConfig()` (dummy) lalu invalidate query supaya kembali sinkron.
 *   - `fetchRoutingConfigs()` mengembalikan array config; yang diedit = config `active`
 *     (fallback: config pertama).
 */

const QUERY_KEY = ['settings-routing-configs'];

const EMPTY_GRAPH: routingTypes.RoutingGraph = { nodes: [], edges: [] };

/** Posisi default node baru (spec §3.5). */
const NEW_NODE_POSITION = { x: 100, y: 100 };

interface ToastState {
  title: string;
  description: string;
  tone: ToastTone;
}

function nextNodeId(nodes: routingTypes.DagNode[]): string {
  const existing = new Set(nodes.map((node) => node.id));
  let index = nodes.length + 1;
  let id = `wc-baru-${index}`;

  while (existing.has(id)) {
    index += 1;
    id = `wc-baru-${index}`;
  }

  return id;
}

function parseCapability(text: string): string[] {
  return text
    .split(',')
    .map((item) => item.trim())
    .filter((item) => item.length > 0);
}

export function RoutingConfigPage() {
  const queryClient = useQueryClient();
  const client = useApiClient();
  const feedback = useFeedback();

  const [draftGraph, setDraftGraph] = useState<routingTypes.RoutingGraph | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [draft, setDraft] = useState<routingTypes.DagNode | null>(null);
  const [capabilityText, setCapabilityText] = useState('');
  const [toast, setToast] = useState<ToastState | null>(null);

  const configs = useQuery({
    queryKey: QUERY_KEY,
    queryFn: () => fetchRoutingConfigs(client),
    staleTime: 30_000,
  });

  const activeConfig: RoutingConfig | undefined = useMemo(() => {
    const rows = configs.data ?? [];

    return rows.find((config) => config.active) ?? rows[0];
  }, [configs.data]);

  const graph = draftGraph ?? activeConfig?.graph ?? EMPTY_GRAPH;

  const save = useMutation({
    mutationFn: (config: RoutingConfig) => saveRoutingConfig(client, config),
    onSuccess: (saved) => {
      feedback.trigger('success');
      setToast({
        title: 'Routing tersimpan',
        description: `Konfigurasi "${saved.name}" tersimpan (${saved.graph.nodes.length} node).`,
        tone: 'success',
      });
      void queryClient.invalidateQueries({ queryKey: QUERY_KEY });
    },
    onError: () => {
      feedback.trigger('error');
      setToast({
        title: 'Gagal menyimpan',
        description: 'Perubahan belum tersimpan. Coba lagi.',
        tone: 'error',
      });
    },
  });

  const handleSelect = useCallback(
    (id: string): void => {
      const node = graph.nodes.find((item) => item.id === id);
      if (node === undefined) return;

      setSelectedId(id);
      setDraft({ ...node, capability: [...(node.capability ?? [])] });
      setCapabilityText((node.capability ?? []).join(', '));
    },
    [graph.nodes],
  );

  const handleDrag = useCallback(
    (id: string, pos: { x: number; y: number }): void => {
      setDraftGraph((previous) => {
        const source = previous ?? activeConfig?.graph;
        if (source === undefined) return previous;

        return {
          nodes: source.nodes.map((node) =>
            node.id === id ? { ...node, position: pos } : node,
          ),
          edges: source.edges,
        };
      });
    },
    [activeConfig],
  );

  function handleAddNode(): void {
    const node: routingTypes.DagNode = {
      id: nextNodeId(graph.nodes),
      label: 'New WC',
      capability: [],
      smv: 0,
      maxWip: 0,
      status: 'idle',
      position: { ...NEW_NODE_POSITION },
    };

    setDraftGraph({ nodes: [...graph.nodes, node], edges: graph.edges });
    setSelectedId(node.id);
    setDraft({ ...node });
    setCapabilityText('');
    setToast({
      title: 'Node ditambahkan',
      description: `${node.id} dibuat di kanvas. Isi propertinya lalu simpan.`,
      tone: 'default',
    });
  }

  function handleApplyChanges(): void {
    if (draft === null) return;

    const updated: routingTypes.DagNode = { ...draft, capability: parseCapability(capabilityText) };

    setDraftGraph({
      nodes: graph.nodes.map((node) => (node.id === updated.id ? updated : node)),
      edges: graph.edges,
    });
    setDraft(updated);
    setToast({
      title: 'Node diperbarui',
      description: `${updated.label} diperbarui di kanvas (klik Simpan untuk mengirim).`,
      tone: 'default',
    });
  }

  function handleDeleteNode(): void {
    if (draft === null) return;

    const removedId = draft.id;

    setDraftGraph({
      nodes: graph.nodes.filter((node) => node.id !== removedId),
      edges: graph.edges.filter((edge) => edge.from !== removedId && edge.to !== removedId),
    });
    setSelectedId(null);
    setDraft(null);
    setCapabilityText('');
    setToast({
      title: 'Node dihapus',
      description: `${draft.label} beserta edge terkait dihapus dari kanvas.`,
      tone: 'default',
    });
  }

  function handleSave(): void {
    if (activeConfig === undefined) return;

    save.mutate({ ...activeConfig, graph });
  }

  function handleReset(): void {
    setDraftGraph(null);
    setSelectedId(null);
    setDraft(null);
    setCapabilityText('');
    setToast({
      title: 'Kanvas direset',
      description: 'Perubahan lokal dibuang, data diambil ulang dari server.',
      tone: 'default',
    });
    void configs.refetch();
  }

  if (configs.isLoading) {
    return (
      <div className="flex min-h-full items-center justify-center p-8">
        <Spinner size="lg" />
      </div>
    );
  }

  if (configs.error !== null || activeConfig === undefined) {
    return (
      <div className="flex min-h-full flex-col items-center justify-center gap-4 p-8">
        <p role="alert" className="text-sm font-semibold text-foreground">
          Gagal memuat konfigurasi routing.
        </p>
        <Button
          variant="secondary"
          onClick={() => {
            void configs.refetch();
          }}
        >
          Coba Lagi
        </Button>
      </div>
    );
  }

  return (
    <div className="flex min-h-full flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title="Routing Configuration"
        subtitle="Editor alur produksi antar work center"
        breadcrumb={[{ label: 'Settings' }, { label: 'Routing' }]}
        actions={
          <span className="self-center text-xs text-muted-foreground">
            {activeConfig.name}
            {draftGraph === null ? '' : ' - ada perubahan belum disimpan'}
          </span>
        }
      />

      <div className="flex min-h-[560px] flex-1 overflow-hidden rounded-card border border-border/40 bg-card">
        <section className="relative flex-[3] overflow-hidden border-r border-border/40">
          <div className="absolute left-4 top-4 z-10 flex flex-wrap gap-2">
            <button
              type="button"
              className={cn(PILL_PRIMARY, 'px-3 py-1.5 text-xs')}
              onClick={handleAddNode}
            >
              <Plus className="h-3.5 w-3.5" aria-hidden="true" />
              Node
            </button>

            <button
              type="button"
              className={cn(PILL_SECONDARY, 'px-3 py-1.5 text-xs')}
              onClick={handleSave}
              disabled={save.isPending}
            >
              <Save className="h-3.5 w-3.5" aria-hidden="true" />
              {save.isPending ? 'Menyimpan...' : 'Simpan'}
            </button>

            <button
              type="button"
              className={cn(PILL_GHOST, 'px-3 py-1.5 text-xs')}
              onClick={handleReset}
            >
              <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" />
              Reset
            </button>
          </div>

          <RoutingGraph
            graph={graph}
            selectedId={selectedId ?? undefined}
            onSelect={handleSelect}
            onDrag={handleDrag}
            className="h-full w-full p-4 pt-20"
          />
        </section>

        <aside className="flex-1 overflow-y-auto p-6">
          {draft === null ? (
            <div className="flex h-full items-center justify-center text-center text-sm text-muted-foreground">
              Pilih node untuk melihat properti
            </div>
          ) : (
            <div className={cn(CARD, 'flex flex-col gap-4')}>
              <h2 className="text-sm font-semibold tracking-tight text-foreground">
                Properties: {draft.label}
              </h2>

              <FormField label="WC Name" htmlFor="node-wc">
                <Input
                  id="node-wc"
                  value={draft.label}
                  onChange={(event) => setDraft({ ...draft, label: event.target.value })}
                />
              </FormField>

              <FormField label="Capability" htmlFor="node-cap">
                <Input
                  id="node-cap"
                  value={capabilityText}
                  placeholder="overlock, single_needle"
                  onChange={(event) => setCapabilityText(event.target.value)}
                />
              </FormField>
              <p className="-mt-2 text-xs text-muted-foreground">
                Pisahkan dengan koma. Contoh: overlock, single_needle
              </p>

              <FormField label="SMV (min/bundle)" htmlFor="node-smv">
                <Input
                  id="node-smv"
                  type="number"
                  min={0}
                  value={String(draft.smv)}
                  onChange={(event) => setDraft({ ...draft, smv: Number(event.target.value) || 0 })}
                />
              </FormField>

              <FormField label="Max WIP" htmlFor="node-wip">
                <Input
                  id="node-wip"
                  type="number"
                  min={0}
                  value={String(draft.maxWip)}
                  onChange={(event) =>
                    setDraft({ ...draft, maxWip: Number(event.target.value) || 0 })
                  }
                />
              </FormField>

              <button
                type="button"
                className={cn(PILL_PRIMARY, 'py-2')}
                onClick={handleApplyChanges}
              >
                Simpan Perubahan
              </button>

              <button
                type="button"
                className={cn(PILL_GHOST, 'py-2 text-accent-coral')}
                onClick={handleDeleteNode}
              >
                <Trash2 className="h-4 w-4" aria-hidden="true" />
                Hapus Node
              </button>
            </div>
          )}
        </aside>
      </div>

      <Toast
        open={toast !== null}
        onOpenChange={(open) => {
          if (!open) setToast(null);
        }}
        title={toast?.title ?? ''}
        description={toast?.description}
        tone={toast?.tone ?? 'default'}
      />
    </div>
  );
}
