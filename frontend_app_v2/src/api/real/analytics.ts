// REAL — adapter analytics (Sprint C.1). Endpoint: /api/v1/analytics/*
// Kontrak: docs/analytics/CONTRACT.md §2–§3.
import type { ApiClient } from '@/integrations/api-client';
import type {
  AnalyticsFilters,
  AnalyticsGroupBy,
  AnalyticsHealth,
  AnalyticsMetricRow,
  AnalyticsPeriod,
  AnalyticsResult,
} from '@/types/analytics';
import { buildQueryPath, getParsed, isRecord, readBool, readNum, readStr } from './_shape';

export const ANALYTICS_METRICS_PATH = (domain: string): string =>
  `/analytics/metrics/${encodeURIComponent(domain)}/`;

export const ANALYTICS_METRIC_PATH = (metricId: string): string =>
  `/analytics/metric/${encodeURIComponent(metricId)}/`;

export const ANALYTICS_HEALTH_PATH = '/analytics/health/';

export interface AnalyticsQuery {
  period?: string | null;
  groupBy?: AnalyticsGroupBy | null;
  granularity?: string | null;
  workCenterId?: number | null;
  lineId?: number | null;
  /** true → `?_nocache=1` (bypass cache 60 dtk). */
  nocache?: boolean;
}

function readQuery(params: AnalyticsQuery): Record<string, string | number | boolean | null> {
  return {
    period: params.period ?? null,
    group_by: params.groupBy ?? null,
    granularity: params.granularity ?? null,
    work_center_id: params.workCenterId ?? null,
    line_id: params.lineId ?? null,
    _nocache: params.nocache ? 1 : null,
  };
}

function readRow(raw: unknown): AnalyticsMetricRow | null {
  if (!isRecord(raw)) return null;

  const row: AnalyticsMetricRow = {
    key: readStr(raw['key']),
    label: readStr(raw['label']),
    unit: readStr(raw['unit']),
    value: raw['value'] === null ? null : readNum(raw['value']),
  };

  for (const key of ['numerator', 'denominator', 'n_bundles', 'incomplete_pairs'] as const) {
    if (typeof raw[key] === 'number') row[key] = raw[key] as number;
  }
  for (const key of ['p50', 'p90'] as const) {
    if (raw[key] === null) row[key] = null;
    else if (typeof raw[key] === 'number') row[key] = raw[key] as number;
  }

  return row;
}

function readFilters(raw: unknown): AnalyticsFilters {
  const source = isRecord(raw) ? raw : {};
  const strOrNull = (value: unknown): string | null =>
    typeof value === 'string' ? value : null;

  return {
    echo: isRecord(source['echo']) ? source['echo'] : {},
    resolved_from: strOrNull(source['resolved_from']),
    resolved_to: strOrNull(source['resolved_to']),
  };
}

function readPeriod(raw: unknown): AnalyticsPeriod {
  const source = isRecord(raw) ? raw : {};
  const strOrNull = (value: unknown): string | null =>
    typeof value === 'string' ? value : null;

  return { from: strOrNull(source['from']), to: strOrNull(source['to']) };
}

function readGroupBy(raw: unknown): AnalyticsGroupBy | null {
  return raw === 'period' || raw === 'work_center' || raw === 'line' ? raw : null;
}

export function readAnalyticsResult(raw: unknown): AnalyticsResult | null {
  if (!isRecord(raw) || !Array.isArray(raw['rows'])) return null;

  const base = {
    filters: readFilters(raw['filters']),
    period: readPeriod(raw['period']),
    generated_at: readStr(raw['generated_at']),
    cached: readBool(raw['cached']),
    historical_data_available: readBool(raw['historical_data_available']),
  };

  if (!readBool(raw['enabled'])) {
    return {
      ...base,
      rows: [],
      summary: {},
      group_by: null,
      enabled: false,
      disabled_reason:
        typeof raw['disabled_reason'] === 'string'
          ? raw['disabled_reason']
          : 'analytics_disabled',
    };
  }

  const rows = raw['rows']
    .map(readRow)
    .filter((row): row is AnalyticsMetricRow => row !== null);

  return {
    ...base,
    rows,
    summary: isRecord(raw['summary']) ? raw['summary'] : {},
    group_by: readGroupBy(raw['group_by']),
    enabled: true,
    disabled_reason: null,
  };
}

export function readAnalyticsHealth(raw: unknown): AnalyticsHealth | null {
  if (!isRecord(raw)) return null;

  const registry = isRecord(raw['registry']) ? raw['registry'] : {};
  const listeners = isRecord(raw['listeners']) ? raw['listeners'] : {};
  const stream = isRecord(raw['stream']) ? raw['stream'] : {};
  const storage = isRecord(raw['storage']) ? raw['storage'] : {};
  const toggle = isRecord(raw['toggle']) ? raw['toggle'] : {};

  return {
    ok: readBool(raw['ok']),
    enabled: readBool(raw['enabled']),
    disabled_reason:
      typeof raw['disabled_reason'] === 'string' ? raw['disabled_reason'] : null,
    registry: {
      metrics_registered: readNum(registry['metrics_registered']),
      metrics_active: readNum(registry['metrics_active']),
    },
    listeners: { subscribed: readNum(listeners['subscribed']) },
    stream: {
      connected: typeof stream['connected'] === 'boolean' ? stream['connected'] : null,
      backend: readStr(stream['backend']),
    },
    storage: {
      snapshots_total: readNum(storage['snapshots_total']),
      last_snapshot_at:
        typeof storage['last_snapshot_at'] === 'string'
          ? storage['last_snapshot_at']
          : null,
      historical_data_available: readBool(storage['historical_data_available']),
    },
    toggle: {
      checked_at: readStr(toggle['checked_at']),
      source: readStr(toggle['source']),
    },
    generated_at: readStr(raw['generated_at']),
  };
}

export async function fetchAnalyticsMetrics(
  client: ApiClient,
  domain: string,
  params: AnalyticsQuery = {},
): Promise<AnalyticsResult> {
  return getParsed(
    client,
    buildQueryPath(ANALYTICS_METRICS_PATH(domain), readQuery(params)),
    readAnalyticsResult,
    'analytics metrics',
  );
}

export async function fetchAnalyticsMetric(
  client: ApiClient,
  metricId: string,
  params: AnalyticsQuery = {},
): Promise<AnalyticsResult> {
  return getParsed(
    client,
    buildQueryPath(ANALYTICS_METRIC_PATH(metricId), readQuery(params)),
    readAnalyticsResult,
    'analytics metric',
  );
}

export async function fetchAnalyticsHealth(client: ApiClient): Promise<AnalyticsHealth> {
  return getParsed(client, ANALYTICS_HEALTH_PATH, readAnalyticsHealth, 'analytics health');
}

