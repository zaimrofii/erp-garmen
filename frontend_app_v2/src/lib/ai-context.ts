/**
 * ai-context.ts — helper PURE konteks chat AI (Sprint E.1).
 *
 * Kontrak: docs/ai/CHAT-CONTRACT.md §4 (tabel page_type) & §5 (validasi).
 * TIDAK menyentuh DOM/HTTP: semua input eksplisit supaya mudah diuji.
 */
import type {
  AIChatChannel,
  AIChatContext,
  AIChatHistoryItem,
  AIChatPageType,
  AIChatRequest,
  AIChatUiMessage,
} from '@/types/ai-chat';

export interface ChatLocation {
  pathname: string;
  search: string;
}

export type ChatFilterValue = string | number | boolean;

const PAGE_TYPES: readonly AIChatPageType[] = ['detail', 'list', 'form', 'report'];

export const MAX_HISTORY_ITEMS = 10;

/** Route ternormalisasi: `pathname + search` (tanpa origin). */
export function normalizeRoute(location: ChatLocation): string {
  return `${location.pathname}${location.search}`;
}

/** Filter dari query string (nilai kosong dilewati; semua string). */
export function filtersFromSearch(search: string): Record<string, string> {
  const params = new URLSearchParams(search.startsWith('?') ? search : `?${search}`);
  const filters: Record<string, string> = {};

  params.forEach((value, key) => {
    if (value.trim().length > 0) filters[key] = value;
  });

  return filters;
}

/**
 * Susun konteks dari halaman aktif.
 *
 * @returns `null` bila `page_type=detail` tetapi `resource_id` tidak ada —
 *          caller harus menampilkan chat tanpa konteks (atau menunggu data).
 */
export function buildChatContext(
  location: ChatLocation,
  params: Readonly<Record<string, string | undefined>>,
  pageType: AIChatPageType | null,
  resourceType: string | null,
  filters: Record<string, ChatFilterValue> = {},
  visibleFields: Record<string, ChatFilterValue> = {},
): AIChatContext | null {
  const resourceId = params['id'] === undefined ? null : String(params['id']);
  if (pageType === 'detail' && (resourceId === null || resourceId.length === 0)) {
    return null;
  }

  const isListLike = pageType === 'list' || pageType === 'report';
  const resolvedFilters =
    isListLike && Object.keys(filters).length === 0
      ? filtersFromSearch(location.search)
      : filters;

  return {
    page_type: pageType,
    route: normalizeRoute(location),
    resource_type: resourceType,
    resource_id: resourceId,
    filters: resolvedFilters,
    visible_fields_snapshot:
      pageType === 'detail' || pageType === 'form' ? visibleFields : {},
  };
}

/** Konteks minimal untuk halaman tanpa resource (§4 baris terakhir). */
export function minimalContext(pathname: string): AIChatContext {
  return {
    page_type: null,
    route: pathname,
    resource_type: null,
    resource_id: null,
    filters: {},
    visible_fields_snapshot: {},
  };
}

export interface ContextValidation {
  ok: boolean;
  reason?: string;
}

/** PURE — validasi §5 #1–#5 (pre-validasi frontend, soft). */
export function validateContextForSubmit(
  context: AIChatContext | null | undefined,
): ContextValidation {
  if (context === null || context === undefined) return { ok: true };

  if (context.page_type !== null && !PAGE_TYPES.includes(context.page_type)) {
    return { ok: false, reason: 'page_type tidak dikenal' };
  }

  const resourceType = context.resource_type;
  const resourceId = context.resource_id;

  if (resourceId !== null) {
    if (typeof resourceId !== 'string' || resourceId.trim().length === 0) {
      return { ok: false, reason: 'resource_id harus string tidak kosong' };
    }
    if (resourceType === null || resourceType.length === 0) {
      return { ok: false, reason: 'resource_type wajib bila resource_id terisi' };
    }
    return { ok: true };
  }

  if (
    resourceType !== null &&
    resourceType.length > 0 &&
    context.page_type !== 'list' &&
    context.page_type !== 'report'
  ) {
    return {
      ok: false,
      reason: 'resource_type wajib null bila resource_id null',
    };
  }

  return { ok: true };
}

/** Riwayat dari pesan UI (maks 10 item, urutan asli). */
export function historyFromMessages(
  messages: readonly AIChatUiMessage[],
): AIChatHistoryItem[] {
  return messages
    .filter((message) => message.content.trim().length > 0)
    .slice(-MAX_HISTORY_ITEMS)
    .map((message) => ({ role: message.role, content: message.content }));
}

/** Susun body request §2 (message + history + context + channel). */
export function buildChatRequest(
  message: string,
  history: readonly AIChatHistoryItem[],
  context: AIChatContext | null | undefined,
  channel: AIChatChannel,
): AIChatRequest {
  return {
    message: message.trim(),
    ...(context === null || context === undefined ? {} : { context }),
    history: history.slice(-MAX_HISTORY_ITEMS),
    channel,
  };
}

/** Label konteks untuk header panel (mis. "Produk: Kaos Polos"). */
export function contextLabel(context: AIChatContext | null): string {
  if (context === null || context.resource_type === null) return 'Tanpa konteks';

  const labels: Record<string, string> = {
    product: 'Produk',
    partner: 'Partner',
    bundle: 'Bundle',
    order: 'Order',
    purchase_order: 'Purchase Order',
    report: 'Laporan',
  };
  const label = labels[context.resource_type] ?? context.resource_type;

  const snapshot = context.visible_fields_snapshot;
  const name = snapshot['name'] ?? snapshot['code'];
  if (name === undefined) return label;

  return `${label}: ${String(name)}`;
}

/** Pesan ramah untuk setiap `error` backend (§6). */
export function chatErrorMessage(error: string): string {
  switch (error) {
    case 'forbidden_context':
      return 'Anda tidak berhak melihat data konteks ini. Ajukan pertanyaan tanpa konteks atau hubungi supervisor.';
    case 'analytics_disabled':
      return 'Analitik belum aktif. Hubungi admin untuk mengaktifkan.';
    case 'not_implemented':
      return 'Fitur AI belum tersedia — chat generik memerlukan LLM (sprint berikutnya).';
    case 'bad_context':
      return 'Konteks tidak valid.';
    case 'network_error':
      return 'Tidak bisa menghubungi server. Periksa koneksi lalu coba lagi.';
    default:
      return 'Asisten AI belum bisa menjawab. Coba lagi.';
  }
}

