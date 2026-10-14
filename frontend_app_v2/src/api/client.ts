import type { ApiClient, ApiResponse } from '@/integrations/api-client';

/**
 * Helper generik: baca `res.data` bila ok, kalau tidak → throw Error berisi pesan.
 * Pemanggil yang butuh 409 handling harus pakai `apiClient` langsung (via ActionButton).
 */
export function unwrap<T>(res: ApiResponse<T>): T {
  if (res.ok && res.data !== undefined) return res.data;
  const msg = res.error?.message ?? `request gagal (status ${res.status})`;
  throw new Error(msg);
}

export type { ApiClient };
