import { useQuery } from '@tanstack/react-query';
import { fetchWorkOrdersKanban } from '@/api/workOrdersKanban';
import type { KanbanQuery } from '@/types/kanban';
import { useApiClient } from './useApiClient';

/**
 * Query key papan kanban work order - SATU sumber untuk pembaca papan dan
 * `useKanbanMove` (optimistic update WAJIB menulis ke key yang sama).
 */
export function workOrdersKanbanQueryKey(params: KanbanQuery = {}) {
  return [
    'work-orders-kanban',
    params.search ?? null,
    params.state ?? null,
    params.work_order_id ?? null,
    params.limit ?? null,
  ] as const;
}

/**
 * useWorkOrdersKanban - React Query wrapper papan kanban work order (FASE K3).
 *
 * Bentuk kartu/kolom SAMA dengan bundle (kontrak K2), jadi `KanbanBoard` bisa dipakai
 * apa adanya; yang berbeda hanya `queryKey` + path endpoint.
 */
export function useWorkOrdersKanban(params: KanbanQuery = {}, enabled = true) {
  const client = useApiClient();

  return useQuery({
    queryKey: workOrdersKanbanQueryKey(params),
    queryFn: () => fetchWorkOrdersKanban(client, params),
    enabled,
    staleTime: 15_000,
  });
}
