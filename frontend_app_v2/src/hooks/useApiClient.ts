import { useMemo } from 'react';
import { createApiClient } from '@/integrations/api-client';
import { readApiBaseUrl } from '@/app/config';
import { ensureDeviceId, readAccessToken } from '@/app/device-identity';

/**
 * Instance ApiClient tunggal per render — sama untuk semua hook.
 * Fase G: header Authorization + X-Device-Id sudah hidup.
 * Catatan: `device-identity` mengekspor `ensureDeviceId`/`readAccessToken`
 * (bukan `getDeviceId`/`getAccessToken`); keduanya cocok dengan kontrak ApiClientConfig.
 */
export function useApiClient() {
  return useMemo(
    () =>
      createApiClient({
        baseUrl: readApiBaseUrl(),
        getDeviceId: ensureDeviceId,
        getAccessToken: readAccessToken,
      }),
    [],
  );
}
