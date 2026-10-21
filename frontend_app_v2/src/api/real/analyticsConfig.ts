// REAL — toggle analytics (Sprint C.2). Endpoint: /api/v1/settings/analytics/* + readiness.
// Kontrak: docs/analytics/TOGGLE-CONTRACT.md §3.
import type { ApiClient } from '@/integrations/api-client';
import type {
  AnalyticsConfig,
  AnalyticsConfigUpdate,
  EnableResponse,
  EnableWarning,
  ReadinessResponse,
} from '@/types/analytics-config';
import { unwrap } from '../client';
import { getParsed, isRecord, readBool, readNum, readStr } from './_shape';

export const SETTINGS_ANALYTICS_PATH = '/settings/analytics/';
export const ANALYTICS_ENABLE_PATH = '/settings/analytics/enable/';
export const ANALYTICS_DISABLE_PATH = '/settings/analytics/disable/';
export const ANALYTICS_READINESS_PATH = '/analytics/readiness/';

function readStringList(raw: unknown): string[] {
  return Array.isArray(raw)
    ? raw.filter((item): item is string => typeof item === 'string')
    : [];
}

function readNumberMap(raw: unknown): Record<string, number> {
  if (!isRecord(raw)) return {};
  return Object.fromEntries(
    Object.entries(raw).filter((entry): entry is [string, number] =>
      typeof entry[1] === 'number',
    ),
  );
}

export function readAnalyticsConfig(raw: unknown): AnalyticsConfig | null {
  if (!isRecord(raw)) return null;

  return {
    enabled: readBool(raw['enabled']),
    enabled_domains: readStringList(raw['enabled_domains']),
    enabled_metrics: readStringList(raw['enabled_metrics']),
    data_readiness_acknowledged_at:
      typeof raw['data_readiness_acknowledged_at'] === 'string'
        ? raw['data_readiness_acknowledged_at']
        : null,
    enabled_by: typeof raw['enabled_by'] === 'number' ? raw['enabled_by'] : null,
    enabled_at: typeof raw['enabled_at'] === 'string' ? raw['enabled_at'] : null,
    disabled_reason: readStr(raw['disabled_reason']),
    historical_data_available: readBool(raw['historical_data_available']),
    updated_at: readStr(raw['updated_at']),
  };
}

export function readReadiness(raw: unknown): ReadinessResponse | null {
  if (!isRecord(raw)) return null;

  return {
    ready: readBool(raw['ready']),
    blockers: readStringList(raw['blockers']),
    soft_blockers: readStringList(raw['soft_blockers']),
    checked_at: readStr(raw['checked_at']),
    thresholds: readNumberMap(raw['thresholds']),
    counts: readNumberMap(raw['counts']),
  };
}

function readWarnings(raw: unknown): EnableWarning[] {
  if (!Array.isArray(raw)) return [];

  return raw
    .map((item) => {
      if (!isRecord(item)) return null;
      return { code: readStr(item['code']), message: readStr(item['message']) };
    })
    .filter((item): item is EnableWarning => item !== null);
}

export function readEnableResponse(raw: unknown): EnableResponse | null {
  const config = readAnalyticsConfig(raw);
  if (config === null || !isRecord(raw)) return null;

  const readiness = readReadiness(raw['readiness']);
  return {
    ...config,
    readiness:
      readiness ?? {
        ready: false,
        blockers: [],
        soft_blockers: [],
        checked_at: '',
        thresholds: {},
        counts: {},
      },
    warnings: readWarnings(raw['warnings']),
  };
}

export async function fetchAnalyticsConfig(client: ApiClient): Promise<AnalyticsConfig> {
  return getParsed(client, SETTINGS_ANALYTICS_PATH, readAnalyticsConfig, 'analytics config');
}

export async function updateAnalyticsConfig(
  client: ApiClient,
  body: AnalyticsConfigUpdate,
): Promise<AnalyticsConfig> {
  const raw = unwrap(
    await client.request<unknown>(SETTINGS_ANALYTICS_PATH, { method: 'PUT', body }),
  );
  const parsed = readAnalyticsConfig(raw);
  if (parsed === null) throw new Error('Bentuk respons analytics config tidak dikenali.');
  return parsed;
}

export async function enableAnalytics(
  client: ApiClient,
  body: Partial<AnalyticsConfigUpdate> = {},
): Promise<EnableResponse> {
  const raw = unwrap(
    await client.post<unknown>(ANALYTICS_ENABLE_PATH, {
      enabled_domains: body.enabled_domains ?? [],
      enabled_metrics: body.enabled_metrics ?? [],
    }),
  );
  const parsed = readEnableResponse(raw);
  if (parsed === null) throw new Error('Bentuk respons enable analytics tidak dikenali.');
  return parsed;
}

export async function disableAnalytics(
  client: ApiClient,
  reason: string,
): Promise<AnalyticsConfig> {
  const cleaned = reason.trim();
  if (cleaned.length === 0) throw new Error('Alasan disable wajib diisi');

  const raw = unwrap(
    await client.post<unknown>(ANALYTICS_DISABLE_PATH, { reason: cleaned }),
  );
  const parsed = readAnalyticsConfig(raw);
  if (parsed === null) throw new Error('Bentuk respons disable analytics tidak dikenali.');
  return parsed;
}

export async function fetchReadiness(client: ApiClient): Promise<ReadinessResponse> {
  return getParsed(client, ANALYTICS_READINESS_PATH, readReadiness, 'analytics readiness');
}

export function readThresholdTotal(raw: Record<string, number>): number {
  return Object.values(raw).reduce((total, value) => total + readNum(value), 0);
}
