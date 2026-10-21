// ADAPTER — analytics (Sprint C.1). Semua mode REAL.
import { pickAdapter } from './_adapter';
import * as real from './real/analytics';

export const fetchAnalyticsMetrics = pickAdapter(
  'analyticsMetrics',
  real.fetchAnalyticsMetrics,
  real.fetchAnalyticsMetrics,
);

export const fetchAnalyticsMetric = pickAdapter(
  'analyticsMetric',
  real.fetchAnalyticsMetric,
  real.fetchAnalyticsMetric,
);

export const fetchAnalyticsHealth = pickAdapter(
  'analyticsHealth',
  real.fetchAnalyticsHealth,
  real.fetchAnalyticsHealth,
);

export { ANALYTICS_HEALTH_PATH, ANALYTICS_METRIC_PATH, ANALYTICS_METRICS_PATH } from './real/analytics';
export type { AnalyticsQuery } from './real/analytics';
export type {
  AnalyticsFilters,
  AnalyticsGroupBy,
  AnalyticsHealth,
  AnalyticsMetricMetadata,
  AnalyticsMetricRow,
  AnalyticsPeriod,
  AnalyticsResponse,
  AnalyticsResult,
  DisabledAnalyticsResponse,
} from '@/types/analytics';
