// REAL - on-time delivery agregat PER ORDER (F3A.CLOSE flip / backend B20b).
// Endpoint: GET /api/v1/reports/on-time-delivery/orders/
import type { ApiClient } from '@/integrations/api-client';
import {
  buildQueryPath,
  getParsed,
  isRecord,
  readListPage,
  readNum,
  readNullableStr,
  readStr,
  type ListPage,
} from './_shape';

export const ON_TIME_DELIVERY_ORDERS_PATH = '/reports/on-time-delivery/orders/';

export interface OtdOrderRow {
  order_code: string;
  deadline: string | null;
  last_wo_finished: string | null;
  on_time: boolean | null;
  /** Jumlah WorkOrder DONE pada order tsb. */
  wo_count: number;
}

function readOnTime(value: unknown): boolean | null {
  return typeof value === 'boolean' ? value : null;
}

/** PURE — respons mentah → `ListPage<OtdOrderRow>`; `null` bila bukan ListPage. */
export function readOtdOrderPage(raw: unknown): ListPage<OtdOrderRow> | null {
  return readListPage<OtdOrderRow>(raw, (row) => {
    if (!isRecord(row)) return null;
    return {
      order_code: readStr(row['order_code']),
      deadline: readNullableStr(row['deadline']),
      last_wo_finished: readNullableStr(row['last_wo_finished']),
      on_time: readOnTime(row['on_time']),
      wo_count: readNum(row['wo_count']),
    };
  });
}

/** PURE — path + `?limit=&cursor=&from=&to=&on_time=`. */
export function buildOtdOrdersPath(
  params: {
    limit?: number | null;
    cursor?: number | null;
    from?: string | null;
    to?: string | null;
    onTime?: boolean | null;
  } = {},
): string {
  return buildQueryPath(ON_TIME_DELIVERY_ORDERS_PATH, {
    limit: params.limit,
    cursor: params.cursor,
    from: params.from,
    to: params.to,
    on_time: params.onTime === null || params.onTime === undefined ? null : params.onTime,
  });
}

/** Baca daftar OTD per order. Gagal HTTP → melempar. */
export async function fetchOnTimeDeliveryOrders(
  client: ApiClient,
  params: {
    limit?: number | null;
    cursor?: number | null;
    from?: string | null;
    to?: string | null;
    onTime?: boolean | null;
  } = {},
): Promise<ListPage<OtdOrderRow>> {
  return getParsed(
    client,
    buildOtdOrdersPath(params),
    readOtdOrderPage,
    'on-time delivery per order',
  );
}
