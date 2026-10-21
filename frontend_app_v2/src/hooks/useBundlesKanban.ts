import { useQuery } from '@tanstack/react-query';
import { fetchBundlesKanban } from '@/api/bundlesKanban';
import type { KanbanQuery } from '@/types/kanban';
import { useApiClient } from './useApiClient';

/**
 * Query key papan kanban bundle - SATU sumber untuk pembaca papan dan
 * `useKanbanMove` (optimistic update WAJIB menulis ke key yang sama).
 */
export function bundlesKanbanQueryKey(params: KanbanQuery = {}) {
  return [
    'bundles-kanban',
    params.search ?? null,
    params.state ?? null,
    params.work_center_id ?? null,
    params.line_id ?? null,
    params.limit ?? null,
  ] as const;
}

/**
 * useBundlesKanban - React Query wrapper papan kanban bundle (FASE K3).
 *
 * `enabled` dipakai halaman: mode `list` TIDAK ikut menarik papan (hemat satu request),
 * sedangkan mode `kanban` menariknya dengan `staleTime` 15 dtk (sama seperti `useBundles`).
 */
export function useBundlesKanban(params: KanbanQuery = {}, enabled = true) {
  const client = useApiClient();

  return useQuery({
    queryKey: bundlesKanbanQueryKey(params),
    queryFn: () => fetchBundlesKanban(client, params),
    enabled,
    staleTime: 15_000,
  });
}
