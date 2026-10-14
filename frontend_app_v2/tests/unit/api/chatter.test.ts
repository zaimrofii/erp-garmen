import { describe, expect, it } from 'vitest';
import { getChatter } from '@/api/chatter';
import type { ApiClient, ApiResponse } from '@/integrations/api-client';
import type { ChatterPage } from '@/lib/schemas/chatter.schema';

/** F1 — D4 paginasi: path chatter memakai `limit` (default 20) + `cursor`. */

const EMPTY_PAGE: ChatterPage = { preview: [], total_count: 0, has_more: false, next_cursor: null };

function stubClient(data: unknown): { client: ApiClient; paths: string[] } {
  const paths: string[] = [];

  const client = {
    get: async <T,>(path: string): Promise<ApiResponse<T>> => {
      paths.push(path);

      return { ok: true, status: 200, data: data as T };
    },
  } as unknown as ApiClient;

  return { client, paths };
}

describe('getChatter — cursor + limit (default 20)', () => {
  it('halaman pertama: limit=20 meski pemanggil tidak mengirim limit', async () => {
    const { client, paths } = stubClient(EMPTY_PAGE);

    const page = await getChatter(client, 'bundles', 16);

    expect(paths).toEqual(['/chatter/bundles/16/?limit=20']);
    expect(page).toEqual(EMPTY_PAGE);
  });

  it('halaman berikutnya: limit + cursor dari `next_cursor`', async () => {
    const { client, paths } = stubClient(EMPTY_PAGE);

    await getChatter(client, 'bundles', 16, { limit: 5, cursor: 'evt-050' });

    expect(paths).toEqual(['/chatter/bundles/16/?limit=5&cursor=evt-050']);
  });

  it('cursor null/kosong → hanya limit (jangan kirim cursor kosong)', async () => {
    const { client, paths } = stubClient(EMPTY_PAGE);

    await getChatter(client, 'bundles', 16, { limit: 5, cursor: null });
    await getChatter(client, 'bundles', 16, { limit: 5, cursor: '   ' });

    expect(paths).toEqual(['/chatter/bundles/16/?limit=5', '/chatter/bundles/16/?limit=5']);
  });
});
