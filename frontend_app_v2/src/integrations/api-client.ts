import type { ConflictPolicy } from "@/lib/conflict-policy";
import { readFilenameFromDisposition } from "@/lib/download";
import { readConflictCurrent } from "./conflict-plan";

/**
 * api-client.ts — SATU-SATUNYA pintu keluar HTTP
 * (larangan §12.1: `fetch()` langsung di komponen; BUKTI 8 Fase 3).
 *
 * Aturan:
 * - Semua kegagalan HTTP → return union, **tidak pernah throw** (`network_error`/`aborted` juga union,
 *   status 0) supaya offline queue & TanStack Query bisa menanganinya dengan tenang.
 * - Header dikirim **hanya kalau nilainya ada** (mis. `X-Force` hanya saat `true`).
 * - Base URL dari config (`VITE_API_BASE_URL`), tidak hardcode.
 */

export interface ApiClientConfig {
  baseUrl: string;
  getDeviceId?: () => string | null;
  getAccessToken?: () => string | null;
}

/** Isi `current` pada respons 409 (dipakai ConflictResolver). */
export interface ApiConflictCurrent {
  version: string;
  state: string;
  current_work_center?: string;
}

export interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  idempotencyKey?: string;
  baseVersion?: string;
  conflictPolicy?: ConflictPolicy;
  /** Retry paksa untuk `last_write_wins` (§8.2) → dikirim sebagai `X-Force: true`. */
  force?: boolean;
  signal?: AbortSignal;
}

export interface ApiErrorPayload {
  kind: string;
  message: string;
  issues?: unknown[];
}

export interface ApiResponse<T> {
  ok: boolean;
  /** 0 = tidak sampai server (network error / abort). */
  status: number;
  data?: T;
  error?: ApiErrorPayload;
  conflict?: { current: ApiConflictCurrent };
  /**
   * F6.2 — sisa waktu (detik) dari header `Retry-After` untuk **429**.
   * Dipakai halaman login untuk pesan "coba lagi dalam X detik"; `undefined`
   * kalau server tidak mengirim header (mis. respons bukan 429).
   */
  retryAfter?: number;
}

export interface ApiClient {
  request<T>(path: string, options?: RequestOptions): Promise<ApiResponse<T>>;
  get<T>(
    path: string,
    options?: Omit<RequestOptions, "method" | "body">,
  ): Promise<ApiResponse<T>>;
  post<T>(
    path: string,
    body: unknown,
    options?: Omit<RequestOptions, "method" | "body">,
  ): Promise<ApiResponse<T>>;
  /**
   * H4.8 — POST yang membalas **berkas binary** (export xlsx/pdf).
   *
   * Additive: `request`/`get`/`post` TIDAK berubah. Error (403/400/500) tetap
   * terstruktur seperti `toErrorPayload`; sukses → `blob` + `filename` (dari
   * `Content-Disposition`) + `contentType`. Tanpa retry otomatis — unduhan
   * diulang manual oleh user.
   */
  requestBlob(
    path: string,
    body: unknown,
    options?: Omit<RequestOptions, "method" | "body">,
  ): Promise<ApiBlobResponse>;
}

/** H4.8 — hasil `requestBlob` (berkas binary + metadata unduhan). */
export interface ApiBlobResponse {
  ok: boolean;
  /** 0 = tidak sampai server (network error / abort). */
  status: number;
  blob?: Blob;
  /** Dari `Content-Disposition: attachment; filename="…"`. */
  filename?: string;
  contentType?: string;
  error?: ApiErrorPayload;
}

const NETWORK_ERROR_STATUS = 0;

/** Prefix API pada baseUrl (`VITE_API_BASE_URL` = `…/api/v1`) — kunci anti double-prefix (D1). */
export const API_PREFIX = "/api/v1";

/**
 * Inventaris endpoint GET yang **butuh sesi** (`IsAuthenticated`) — dokumentasi + uji drift.
 *
 * ⚠️ FIX 403 (H3.4): daftar ini **BUKAN lagi gerbang keputusan**. Sebelumnya
 * `isAuthScopedGetPath()` men-cocokkan daftar ini (allowlist), sehingga endpoint sesi yang
 * lupa didaftarkan → request GET tanpa `sessionid` → backend membalas **403** walau user
 * sudah login (kejadian nyata: `/master/*` — semua halaman `/inventory/*` memuat master lewat
 * React Query — dan `/routing/graph/`). Sejak fix, gerbangnya **DIBALIK**: cookie dikirim
 * untuk SEMUA request kecuali prefix yang eksplisit publik (`PUBLIC_GET_PREFIXES`).
 *
 * Daftar tetap dirawat karena: (1) mencatat endpoint sesi per fase (F1.6/F7/F9, H1-H3);
 * (2) dipakai uji drift + uji anti-kontradiksi di
 * `tests/unit/integrations/api-client.test.ts` supaya endpoint sesi baru selalu terdaftar.
 */
export const AUTH_SCOPED_GET_PREFIXES = [
  "/sync/",
  "/audit/",
  "/reconciliation/",
  "/garmen/orders/",
  "/settings/",
  "/ai/",
  "/inventory/",
  "/auth/",
  // F7 — endpoint IsAuthenticated yang belum tercakup (dashboard/production/quality/reports/purchase/finance)
  "/dashboard/",
  "/production/",
  "/quality/",
  "/reports/",
  "/purchase/",
  "/finance/",
  "/master/",
  "/routing/",
] as const;

const ABSOLUTE_URL_PATTERN = /^[a-z][a-z0-9+.-]*:\/\//i;
const CSRF_COOKIE_NAME = "csrftoken";

/** PURE — true kalau `value` URL absolut (`http(s)://…`) → JANGAN prepend baseUrl (D1). */
export function isAbsoluteUrl(value: string): boolean {
  return ABSOLUTE_URL_PATTERN.test(value.trim());
}

/**
 * PURE — D1: URL final sebuah request.
 *
 * `endpoint` dari metadata **relatif** ke `baseUrl` yang sudah termasuk `/api/v1`, jadi
 * prefix tidak boleh ditambahkan dua kali:
 * 1. URL absolut (`http(s)://…`) → dipakai apa adanya;
 * 2. path yang sudah membawa `/api/v1` padahal baseUrl juga ber-prefix itu → di-dedupe;
 * 3. sisanya → `baseUrl + path`.
 */
export function buildRequestUrl(baseUrl: string, path: string): string {
  const candidate = path.trim();
  const base = baseUrl.trim().replace(/\/+$/, "");

  if (candidate.length === 0) return base;
  if (isAbsoluteUrl(candidate)) return candidate;
  if (base.length === 0) return candidate;

  const normalized =
    base.endsWith(API_PREFIX) && candidate.startsWith(API_PREFIX)
      ? candidate.slice(API_PREFIX.length)
      : candidate;

  const withSlash = normalized.startsWith("/") ? normalized : `/${normalized}`;

  return `${base}${withSlash}`;
}

/**
 * Prefix API yang **publik** (`AllowAny` di backend) → GET-nya TIDAK perlu cookie.
 *
 * Sejak FIX 403 (H3.4) daftar ini adalah **satu-satunya** pengecualian: semua path lain
 * (termasuk endpoint baru yang belum terdaftar di mana pun) dianggap butuh sesi, jadi lupa
 * mendaftarkan endpoint baru TIDAK lagi berakibat 403 senyap.
 *
 * Bukti probe live (dev, `VITE_API_BASE_URL` = `http://localhost:8000/api/v1`, origin
 * `http://localhost:5173`):
 *
 *   GET /api/v1/devices/me          -> 200 anonim (`AllowAny`, fallback profile);
 *   GET /api/v1/garmen/bundles/     -> 200 anonim (resource generik F2, `AllowAny`);
 *   GET /api/v1/garmen/order-lines/ -> 200 anonim (idem);
 *   GET /api/v1/metadata/<resource> -> `MetadataView` (`AllowAny`);
 *   GET /api/v1/chatter/            -> `ChatterView` (`AllowAny`, "auth menyusul Fase 6").
 *
 * Endpoint SESI yang dulu bolong (kini ikut default aman):
 *   GET /api/v1/master/uoms/    -> 403 anonim / 200 ber-sesi;
 *   GET /api/v1/routing/graph/  -> 403 anonim / 200 ber-sesi.
 */
export const PUBLIC_GET_PREFIXES = [
  "/metadata/",
  "/chatter/",
  "/devices/",
  "/garmen/bundles/",
  "/garmen/order-lines/",
] as const;

/**
 * PURE — normalkan path request supaya cocok walau ditulis lengkap.
 *
 * Prefix `/api/v1` dibuang (klien boleh menulis `/master/uoms/` MAUPUN
 * `/api/v1/master/uoms/`; `buildRequestUrl` sudah meng-dedupe prefix itu) dan path dipastikan
 * berawalan `/`. Query tetap dipertahankan karena pemanggil hanya membandingkan prefix.
 */
export function normalizeApiPath(path: string): string {
  const candidate = path.trim();
  const withoutApiPrefix = candidate.startsWith(API_PREFIX)
    ? candidate.slice(API_PREFIX.length)
    : candidate;

  return withoutApiPrefix.startsWith("/") ? withoutApiPrefix : `/${withoutApiPrefix}`;
}

/**
 * PURE — true kalau GET ini **butuh sesi** (default), false hanya untuk prefix publik.
 *
 * Logikanya "default aman" (lihat `PUBLIC_GET_PREFIXES` untuk alasan + bukti probe).
 */
export function isAuthScopedGetPath(path: string): boolean {
  const candidate = normalizeApiPath(path);

  return !PUBLIC_GET_PREFIXES.some((prefix) => candidate.startsWith(prefix));
}

/**
 * PURE — apakah request ini butuh kredensial (D5): SEMUA tulis + semua GET kecuali prefix
 * publik. Sejak F1.6 nilainya dipakai apa adanya (tanpa syarat same-origin).
 *
 * FIX 403 (H3.4): sebelumnya GET hanya "bercookie" kalau prefix-nya terdaftar di allowlist
 * `AUTH_SCOPED_GET_PREFIXES` -> `/master/*` (dan `/routing/graph/`) terlewat -> 403 walau user
 * sudah login. Kini `isAuthScopedGetPath()` memakai default-aman (bukan-publik = butuh sesi).
 */
export function needsCredentials(method: string, path: string): boolean {
  return method !== "GET" || isAuthScopedGetPath(path);
}

/** PURE — origin halaman; `null` kalau tidak tersedia (SSR/test). */
export function readPageOrigin(): string | null {
  const origin = globalThis.location?.origin;

  return typeof origin === "string" && origin.length > 0 ? origin : null;
}

/**
 * PURE — true kalau URL menuju origin BERBEDA dari halaman.
 *
 * **Sejak F1.6 helper ini TIDAK lagi dipakai untuk menggating credentials**: backend dev
 * sudah mengirim `Access-Control-Allow-Credentials: true` (F1.5), sehingga `credentials:
 * 'include'` aman lintas origin. Dipertahankan sebagai diagnosa + test
 * (`tests/unit/integrations/api-client.test.ts`).
 *
 * Origin tidak diketahui (`null`) → dianggap same-origin (SSR/test/produksi satu domain).
 */
export function isCrossOriginRequest(
  url: string,
  pageOrigin: string | null = readPageOrigin(),
): boolean {
  if (pageOrigin === null) return false;
  if (!isAbsoluteUrl(url)) return false;

  try {
    return new URL(url).origin !== pageOrigin;
  } catch {
    return false;
  }
}

/** PURE — baca satu cookie dari string `document.cookie` (SSR-safe, tanpa regex). */
export function readCookieValue(cookie: string, name: string): string | null {
  for (const part of cookie.split(";")) {
    const separator = part.indexOf("=");
    if (separator < 0) continue;
    if (part.slice(0, separator).trim() !== name) continue;

    const value = part.slice(separator + 1).trim();

    return value.length > 0 ? value : null;
  }

  return null;
}

/**
 * Token CSRF dari cookie `csrftoken` (D5) — cookie Django ini non-HttpOnly, jadi bisa
 * dibaca JS. `null` (mis. lintas origin, cookie belum ada) → header `X-CSRFToken` TIDAK
 * dikirim (jangan kirim string kosong).
 */
export function readCsrfToken(cookie?: string): string | null {
  const source = cookie ?? globalThis.document?.cookie ?? "";

  return readCookieValue(source, CSRF_COOKIE_NAME);
}

/**
 * PURE — detik dari header `Retry-After` (F6.2).
 *
 * Backend `core.auth.ratelimit` mengirim **angka detik** (`Retry-After: 42`), jadi hanya
 * bentuk angka yang dibaca; format tanggal HTTP (`Wed, 21 Oct …`) diabaikan → `null`
 * supaya pemanggil memakai nilai default, bukan `NaN`.
 */
export function readRetryAfterSeconds(value: string | null): number | null {
  if (value === null) return null;

  const seconds = Number.parseInt(value.trim(), 10);

  return Number.isFinite(seconds) && seconds > 0 ? seconds : null;
}

function buildHeaders(
  config: ApiClientConfig,
  options: RequestOptions,
): Record<string, string> {
  const headers: Record<string, string> = {};

  if (options.body !== undefined) headers["Content-Type"] = "application/json";

  const token = config.getAccessToken?.() ?? null;
  if (typeof token === "string" && token.length > 0)
    headers["Authorization"] = `Bearer ${token}`;

  const deviceId = config.getDeviceId?.() ?? null;
  if (typeof deviceId === "string" && deviceId.length > 0)
    headers["X-Device-Id"] = deviceId;

  if (
    typeof options.idempotencyKey === "string" &&
    options.idempotencyKey.length > 0
  ) {
    headers["Idempotency-Key"] = options.idempotencyKey;
  }
  if (
    typeof options.baseVersion === "string" &&
    options.baseVersion.length > 0
  ) {
    headers["X-Base-Version"] = options.baseVersion;
  }
  if (options.conflictPolicy !== undefined)
    headers["X-Conflict-Policy"] = options.conflictPolicy;
  if (options.force === true) headers["X-Force"] = "true";

  return headers;
}

interface ReadResult {
  /** true = body valid JSON (atau kosong). */
  parsed: boolean;
  value: unknown;
}

async function readBody(response: Response): Promise<ReadResult> {
  const text = await response.text();
  if (text.length === 0) return { parsed: true, value: undefined };

  try {
    return { parsed: true, value: JSON.parse(text) as unknown };
  } catch {
    return { parsed: false, value: text };
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * D3: `current` dibaca dari body yang sudah diparse — urutan prioritas (top-level dulu,
 * alias `conflict.current` fallback) ada di `conflict-plan.readConflictCurrent`.
 */
function readConflictCurrentFromBody(
  body: ReadResult,
): ApiConflictCurrent | undefined {
  if (!body.parsed) return undefined;

  return readConflictCurrent(body.value);
}

function toErrorPayload(body: ReadResult, status: number): ApiErrorPayload {
  if (body.parsed && isRecord(body.value)) {
    const kind = body.value["kind"];
    const message = body.value["message"];
    const issues = body.value["issues"];
    // F6.2 — DRF membalas `{"detail": "…"}` (semua endpoint backend memakai bentuk ini).
    // Tanpa cabang ini pesan server hilang dan klien hanya melihat "HTTP 400/401".
    const detail = body.value["detail"];

    const text =
      typeof message === "string"
        ? message
        : typeof detail === "string" && detail.length > 0
          ? detail
          : `HTTP ${status}`;

    const payload: ApiErrorPayload = {
      kind: typeof kind === "string" ? kind : "http_error",
      message: text,
    };
    if (Array.isArray(issues)) payload.issues = issues;
    return payload;
  }

  if (body.parsed && typeof body.value === "string" && body.value.length > 0) {
    return {
      kind: "http_error",
      message: `HTTP ${status}: ${body.value.slice(0, 200)}`,
    };
  }

  if (!body.parsed) {
    const raw = typeof body.value === "string" ? body.value.slice(0, 200) : "";
    return {
      kind: "invalid_json",
      message: `HTTP ${status}: respons bukan JSON${raw.length > 0 ? ` — ${raw}` : ""}`,
    };
  }

  return { kind: "http_error", message: `HTTP ${status}` };
}

function isAbortError(caught: unknown): boolean {
  return caught instanceof Error && caught.name === "AbortError";
}

function toNetworkError<T>(caught: unknown): ApiResponse<T> {
  return {
    ok: false,
    status: NETWORK_ERROR_STATUS,
    error: {
      kind: isAbortError(caught) ? "aborted" : "network_error",
      message:
        caught instanceof Error
          ? caught.message
          : "Permintaan gagal (network).",
    },
  };
}

async function toApiResponse<T>(response: Response): Promise<ApiResponse<T>> {
  const status = response.status;
  const body = await readBody(response);

  if (status === 409) {
    const current = readConflictCurrentFromBody(body);
    const result: ApiResponse<T> = {
      ok: false,
      status,
      error: {
        kind: "conflict",
        message: toErrorPayload(body, status).message,
      },
    };
    if (current !== undefined) result.conflict = { current };
    return result;
  }

  if (status >= 200 && status < 300) {
    return {
      ok: true,
      status,
      data: body.parsed ? (body.value as T) : undefined,
    };
  }

  const failed: ApiResponse<T> = {
    ok: false,
    status,
    error: toErrorPayload(body, status),
  };

  // F6.2 — 429 endpoint auth membawa `Retry-After` (detik); dioper supaya UI bisa
  // menampilkan "coba lagi dalam X detik" tanpa membaca header sendiri di komponen.
  const retryAfter = readRetryAfterSeconds(response.headers.get("Retry-After"));
  if (retryAfter !== null) failed.retryAfter = retryAfter;

  return failed;
}

export function createApiClient(config: ApiClientConfig): ApiClient {
  async function request<T>(
    path: string,
    options: RequestOptions = {},
  ): Promise<ApiResponse<T>> {
    const method = options.method ?? "GET";
    const url = buildRequestUrl(config.baseUrl, path);
    const headers = buildHeaders(config, options);

    // D5: CSRF hanya untuk request tulis (GET aman by design Django).
    if (method !== "GET") {
      const csrfToken = readCsrfToken();
      if (csrfToken !== null) headers["X-CSRFToken"] = csrfToken;
    }

    const init: RequestInit = { method, headers };

    // D5 + F1.6 + FIX 403 (H3.4): cookie (sessionid/csrftoken) untuk semua tulis + semua GET
    // kecuali prefix publik (`PUBLIC_GET_PREFIXES`, lihat `needsCredentials`) — TERMASUK lintas
    // origin. Sejak F1.5 backend dev mengirim `Access-Control-Allow-Credentials: true`
    // (`CORS_ALLOW_CREDENTIALS=True` di `django_app/.env`), jadi syarat same-origin dibuang.
    if (needsCredentials(method, path)) {
      init.credentials = "include";
    }

    if (options.body !== undefined) init.body = JSON.stringify(options.body);
    if (options.signal !== undefined) init.signal = options.signal;

    let response: Response;
    try {
      response = await fetch(url, init);
    } catch (caught) {
      return toNetworkError<T>(caught);
    }

    return await toApiResponse<T>(response);
  }

  async function requestBlob(
    path: string,
    body: unknown,
    options: Omit<RequestOptions, "method" | "body"> = {},
  ): Promise<ApiBlobResponse> {
    const url = buildRequestUrl(config.baseUrl, path);
    const headers = buildHeaders(config, { ...options, body });

    // D5: CSRF untuk request tulis (unduhan = POST) — pola sama `request`.
    const csrfToken = readCsrfToken();
    if (csrfToken !== null) headers["X-CSRFToken"] = csrfToken;

    const init: RequestInit = {
      method: "POST",
      headers,
      body: JSON.stringify(body ?? {}),
    };
    if (needsCredentials("POST", path)) init.credentials = "include";
    if (options.signal !== undefined) init.signal = options.signal;

    let response: Response;
    try {
      response = await fetch(url, init);
    } catch (caught) {
      return {
        ok: false,
        status: NETWORK_ERROR_STATUS,
        error: toNetworkError<unknown>(caught).error,
      };
    }

    const status = response.status;
    if (status < 200 || status >= 300) {
      // Server membalas galat JSON (DRF `{"detail": "…"}`) — bukan berkas.
      return { ok: false, status, error: toErrorPayload(await readBody(response), status) };
    }

    const result: ApiBlobResponse = {
      ok: true,
      status,
      blob: await response.blob(),
      contentType: response.headers.get("Content-Type") ?? "",
    };
    const filename = readFilenameFromDisposition(
      response.headers.get("Content-Disposition"),
    );
    if (filename !== null) result.filename = filename;
    return result;
  }

  return {
    request,
    get: (path, options) => request(path, { ...options, method: "GET" }),
    post: (path, body, options) =>
      request(path, { ...options, method: "POST", body }),
    requestBlob,
  };
}
