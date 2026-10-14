import { useQuery } from '@tanstack/react-query';
import { useApiClient } from './useApiClient';
import { getBundle } from '@/api/bundles';

export function useBundle(id: number | string | undefined) {
  const client = useApiClient();
  return useQuery({
    queryKey: ['bundle', String(id)],
    queryFn: () => getBundle(client, id!),
    enabled: id != null,
    staleTime: 15_000,
  });
}
