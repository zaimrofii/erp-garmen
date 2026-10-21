// ADAPTER — toggle analytics (Sprint C.2). Semua mode REAL.
import { pickAdapter } from './_adapter';
import * as real from './real/analyticsConfig';

export const fetchAnalyticsConfig = pickAdapter(
  'analyticsConfig',
  real.fetchAnalyticsConfig,
  real.fetchAnalyticsConfig,
);

export const fetchAnalyticsReadiness = pickAdapter(
  'analyticsReadiness',
  real.fetchReadiness,
  real.fetchReadiness,
);

export { updateAnalyticsConfig, enableAnalytics, disableAnalytics } from './real/analyticsConfig';
export {
  ANALYTICS_DISABLE_PATH,
  ANALYTICS_ENABLE_PATH,
  ANALYTICS_READINESS_PATH,
  SETTINGS_ANALYTICS_PATH,
} from './real/analyticsConfig';
export type {
  AnalyticsConfig,
  AnalyticsConfigUpdate,
  EnableResponse,
  EnableWarning,
  ReadinessResponse,
} from '@/types/analytics-config';
