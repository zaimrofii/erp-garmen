import { useQuery } from '@tanstack/react-query';
import { useApiClient } from './useApiClient';
import { getChatter } from '@/api/chatter';

export function useChatter(
  resource: string,
  id: number | string | undefined,
  params: { limit?: number | null; cursor?: string | null } = {},
) {
  const client = useApiClient();
  return useQuery({
    queryKey: ['chatter', resource, String(id), params.limit ?? null, params.cursor ?? null],
    queryFn: () => getChatter(client, resource, id!, params),
    enabled: id != null,
    staleTime: 10_000,
  });
}
