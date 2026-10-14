import { useQuery } from '@tanstack/react-query';
import { useApiClient } from './useApiClient';
import { getBundles } from '@/api/bundles';

export function useBundles(params: { limit?: number; offset?: number } = {}) {
  const client = useApiClient();
  return useQuery({
    queryKey: ['bundles', params.limit ?? null, params.offset ?? null],
    queryFn: () => getBundles(client, params),
    staleTime: 15_000,
  });
}
