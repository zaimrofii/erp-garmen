import { useQuery } from '@tanstack/react-query';
import { useApiClient } from './useApiClient';
import { getWorkOrders } from '@/api/workOrders';

export function useWorkOrders(params: { limit?: number; offset?: number } = {}) {
  const client = useApiClient();
  return useQuery({
    queryKey: ['work-orders', params.limit ?? null, params.offset ?? null],
    queryFn: () => getWorkOrders(client, params),
    staleTime: 15_000,
  });
}
