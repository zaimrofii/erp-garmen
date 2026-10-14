  import { openDB, type DBSchema, type IDBPDatabase } from 'idb';
  import type { ConflictPolicy } from '@/lib/conflict-policy';
  import { generateUUID } from '@/lib/uuid';
  import type { ApiClient, ApiConflictCurrent, ApiResponse } from './api-client';

  /**
   * offline-queue.ts — IndexedDB queue + atomic flush + expected_result + conflict policy.
   *
   * Sabuk pengaman: #2 Atomic Offline Queue · #3 Idempotency-Key · #9 Conflict Policy (3-mode)
   * · #10 Expected-Result Validator — alur lengkap di prototype-v6.1 §8.3.
   *
   * Aturan yang dipegang:
   * - **Atomic**: item dihapus satu per satu (`remove(id)`) — TIDAK PERNAH `queue = []` di luar loop (§12.3).
   * - **`Idempotency-Key`** dibuat SEKALI saat enqueue (`generateUUID()`), bukan saat kirim.
   * - `flush()` **sequential** supaya dependency teratur; dependency `failed` → **skip & lanjut**
   *   (bukan `break` → queue tidak stuck), dependency `pending` → break (tunggu).
   * - DB dibuka **lazy** → aman di-import tanpa IndexedDB (SSR/test) dan mudah di-shim `fake-indexeddb`.
   */

  export interface ExpectedResult {
    state?: string;
    fields?: Record<string, unknown>;
  }

  export interface OfflineAction {
    /** `generateUUID()` — bukan `crypto.randomUUID()` langsung (§12.3). */
    id: string;
    path: string;
    method: 'POST' | 'PUT' | 'PATCH' | 'DELETE';
    body: unknown;
    /** Untuk invalidate query + per-resource lock (Fase 4). */
    resource: string;
    resourceId: string;
    ts: number;
    base_version: string;
    expected_result?: ExpectedResult;
    conflict_policy: ConflictPolicy;
    /** id `OfflineAction` lain yang harus sukses lebih dulu. */
    depends_on?: string;
    status: 'pending' | 'flushing' | 'conflict' | 'failed';
    error?: string;
    idempotency_key: string;
  }

  export type EnqueueInput = Omit<
    OfflineAction,
    'id' | 'ts' | 'status' | 'error' | 'idempotency_key'
  >;

  export type DependencyState = 'success' | 'failed' | 'pending';
  export type FlushBucket = 'succeeded' | 'failed' | 'conflicted' | 'skipped';

  /** Hasil PER-AKSI (objek, bukan string) supaya UI bisa menampilkan alasan/konflik. */
  export interface FlushOutcome {
    id: string;
    resource: string;
    resourceId: string;
    path: string;
    /** HTTP status; 0 = network error. */
    status: number;
    reason?: string;
    /** Hanya untuk 409 (ConflictResolver). */
    current?: ApiConflictCurrent;
    /** true = item masih tersimpan di queue (tidak dihapus). Item `pending` akan dicoba lagi;
        `conflict` / dependency-failed butuh tindakan operator. */
    kept: boolean;
  }

  export interface FlushResult {
    /** Jumlah aksi yang benar-benar dicoba (item yang ter-break oleh dependency pending tidak dihitung). */
    processed: number;
    succeeded: FlushOutcome[];
    failed: FlushOutcome[];
    conflicted: FlushOutcome[];
    /** Dependency gagal → aksi ditandai `failed` dan dilewati (queue tetap jalan). */
    skipped: FlushOutcome[];
    /** true bila `navigator.onLine === false` saat flush dipanggil (tidak ada request dikirim). */
    offline: boolean;
    /** Sisa item di queue setelah flush (badge UI). */
    pendingAfter: number;
    /** Resource yang statusnya berubah → bahan invalidate query (§8.3 langkah 8). */
    touchedResources: string[];
  }

  export interface OfflineQueueConfig {
    apiClient: ApiClient;
    /** Default `mes-offline-queue`. */
    dbName?: string;
    onMismatch?: (action: OfflineAction, outcome: FlushOutcome) => void;
    onConflict?: (action: OfflineAction, outcome: FlushOutcome) => void;
    onFlushComplete?: (result: FlushResult) => void;
  }

  export interface OfflineQueue {
    /** → id aksi. `Idempotency-Key` dibuat di sini (sekali). */
    enqueue(input: EnqueueInput): Promise<string>;
    size(): Promise<number>;
    list(): Promise<OfflineAction[]>;
    get(id: string): Promise<OfflineAction | undefined>;
    remove(id: string): Promise<void>;
    clear(): Promise<void>;
    flush(): Promise<FlushResult>;
  }

  interface QueueSchema extends DBSchema {
    actions: { key: string; value: OfflineAction };
  }

  const DEFAULT_DB_NAME = 'mes-offline-queue';
  const STORE = 'actions';

  /**
   * PURE — dipanggil caller dengan Map aksi yang sedang diketahui.
   * - `depends_on` kosong / dependency sudah tidak ada di map (berarti sudah sukses & dihapus) → `success`
   * - dependency `failed` atau `conflict` (butuh resolve manual, tak akan sukses sendiri) → `failed`
   * - dependency `pending`/`flushing` → `pending` (tunggu, jangan proses dulu)
   */
  export function resolveDependency(
    action: OfflineAction,
    byId: Map<string, OfflineAction>
  ): DependencyState {
    const dependencyId = action.depends_on;
    if (dependencyId === undefined) return 'success';

    const dependency = byId.get(dependencyId);
    if (dependency === undefined) return 'success';
    if (dependency.status === 'failed' || dependency.status === 'conflict') return 'failed';

    return 'pending';
  }

  function readOnline(): boolean {
    const navigatorLike = globalThis as { navigator?: { onLine?: boolean } };
    return navigatorLike.navigator?.onLine !== false;
  }

  export function createOfflineQueue(config: OfflineQueueConfig): OfflineQueue {
    let dbPromise: Promise<IDBPDatabase<QueueSchema>> | null = null;

    function db(): Promise<IDBPDatabase<QueueSchema>> {
      if (dbPromise === null) {
        dbPromise = openDB<QueueSchema>(config.dbName ?? DEFAULT_DB_NAME, 1, {
          upgrade(database) {
            if (!database.objectStoreNames.contains(STORE)) {
              database.createObjectStore(STORE, { keyPath: 'id' });
            }
          },
        });
      }
      return dbPromise;
    }

    async function readAll(): Promise<OfflineAction[]> {
      const database = await db();
      const actions = await database.getAll(STORE);
      return actions.sort((left, right) => left.ts - right.ts);
    }

    /* ---- helper hasil ---- */

    function isRecordLike(value: unknown): value is Record<string, unknown> {
      return typeof value === 'object' && value !== null && !Array.isArray(value);
    }

    function buildOutcome(
      action: OfflineAction,
      detail: { status: number; reason?: string; current?: ApiConflictCurrent; kept: boolean }
    ): FlushOutcome {
      const result: FlushOutcome = {
        id: action.id,
        resource: action.resource,
        resourceId: action.resourceId,
        path: action.path,
        status: detail.status,
        kept: detail.kept,
      };
      if (detail.reason !== undefined) result.reason = detail.reason;
      if (detail.current !== undefined) result.current = detail.current;
      return result;
    }

    /** §8.3 langkah 5 — mismatch WAJIB terdeteksi, jangan diabaikan (§12.3). */
    function checkExpectedResult(action: OfflineAction, data: unknown): string | null {
      const expected = action.expected_result;
      if (expected === undefined) return null;

      if (!isRecordLike(data)) return 'expected_result_unavailable';

      if (expected.state !== undefined && data['state'] !== expected.state) {
        return `expected_state_mismatch:${String(data['state'])}`;
      }

      if (expected.fields !== undefined) {
        for (const [key, value] of Object.entries(expected.fields)) {
          if (data[key] !== value) return `expected_field_mismatch:${key}`;
        }
      }

      return null;
    }

    interface FlushContext {
      byId: Map<string, OfflineAction>;
      touched: Set<string>;
    }

    interface Resolved {
      bucket: FlushBucket;
      outcome: FlushOutcome;
    }

    async function removeAction(action: OfflineAction, context: FlushContext): Promise<void> {
      const database = await db();
      await database.delete(STORE, action.id);
      context.byId.delete(action.id);
      context.touched.add(action.resource);
    }

    async function keepAction(
      action: OfflineAction,
      patch: Partial<OfflineAction>,
      context: FlushContext
    ): Promise<OfflineAction> {
      const updated: OfflineAction = { ...action, ...patch };
      const database = await db();
      await database.put(STORE, updated);
      context.byId.set(updated.id, updated);
      return updated;
    }

    /* ---- handler per-kondisi ---- */

    async function handleSuccess(
      action: OfflineAction,
      response: ApiResponse<unknown>,
      context: FlushContext
    ): Promise<Resolved> {
      const mismatch = checkExpectedResult(action, response.data);

      if (mismatch !== null) {
        await removeAction(action, context);
        const result = buildOutcome(action, {
          status: response.status,
          reason: mismatch,
          kept: false,
        });
        config.onMismatch?.(action, result);
        return { bucket: 'failed', outcome: result };
      }

      await removeAction(action, context);
      return {
        bucket: 'succeeded',
        outcome: buildOutcome(action, { status: response.status, kept: false }),
      };
    }

    async function handleHttpError(
      action: OfflineAction,
      response: ApiResponse<unknown>,
      context: FlushContext
    ): Promise<Resolved> {
      const kind = response.error?.kind ?? 'http_error';
      const message = response.error?.message ?? `HTTP ${response.status}`;

      // 5xx / network → item TETAP pending + error diisi (bukan dihapus) supaya bisa dicoba lagi.
      if (response.status >= 500 || response.status === 0) {
        const kept = await keepAction(
          action,
          { status: 'pending', error: `${kind}: ${message}` },
          context
        );
        return {
          bucket: 'failed',
          outcome: buildOutcome(kept, { status: response.status, reason: kind, kept: true }),
        };
      }

      // 4xx selain 409 → tidak akan berhasil kalau diulang: hapus + catat failed.
      await removeAction(action, context);
      return {
        bucket: 'failed',
        outcome: buildOutcome(action, {
          status: response.status,
          reason: `http_${response.status}`,
          kept: false,
        }),
      };
    }

    async function handleConflict(
      action: OfflineAction,
      response: ApiResponse<unknown>,
      context: FlushContext
    ): Promise<Resolved> {
      const current = response.conflict?.current;

      // server_wins (§8.2) — server lebih akurat: lepas aksi lokal, tandai conflicted.
      if (action.conflict_policy === 'server_wins') {
        await removeAction(action, context);
        return {
          bucket: 'conflicted',
          outcome: buildOutcome(action, {
            status: 409,
            reason: 'conflict_server_wins',
            current,
            kept: false,
          }),
        };
      }

      // last_write_wins (§8.2) — operator lihat fisik: retry paksa TANPA X-Base-Version.
      // Kalau 409 lagi → jatuh ke manual (jangan retry tanpa batas).
      if (action.conflict_policy === 'last_write_wins') {
        const forced = await config.apiClient.post<unknown>(action.path, action.body, {
          idempotencyKey: action.idempotency_key,
          conflictPolicy: 'last_write_wins',
          force: true,
        });

        if (forced.status !== 409) return await interpret(action, forced, context);
      }

      // manual (default) — butuh operator: item TETAP di queue dengan status 'conflict'.
      const kept = await keepAction(
        action,
        {
          status: 'conflict',
          error: `conflict_manual${current === undefined ? '' : `:${current.version}`}`,
        },
        context
      );
      const result = buildOutcome(kept, {
        status: 409,
        reason: 'conflict_manual',
        current,
        kept: true,
      });
      config.onConflict?.(action, result);
      return { bucket: 'conflicted', outcome: result };
    }

    async function interpret(
      action: OfflineAction,
      response: ApiResponse<unknown>,
      context: FlushContext
    ): Promise<Resolved> {
      if (response.status === 409) return await handleConflict(action, response, context);
      if (!response.ok) return await handleHttpError(action, response, context);
      return await handleSuccess(action, response, context);
    }

    async function submit(action: OfflineAction, context: FlushContext): Promise<Resolved> {
      const response = await config.apiClient.post<unknown>(action.path, action.body, {
        idempotencyKey: action.idempotency_key,
        baseVersion: action.base_version,
        conflictPolicy: action.conflict_policy,
      });

      return await interpret(action, response, context);
    }

    async function flush(): Promise<FlushResult> {
      const database = await db();
      const result: FlushResult = {
        processed: 0,
        succeeded: [],
        failed: [],
        conflicted: [],
        skipped: [],
        offline: false,
        pendingAfter: 0,
        touchedResources: [],
      };

      // Offline → jangan kirim apa pun (bukan error, hanya ditunda).
      if (!readOnline()) {
        result.offline = true;
        result.pendingAfter = await database.count(STORE);
        config.onFlushComplete?.(result);
        return result;
      }

      const all = await readAll();
      const context: FlushContext = {
        byId: new Map(all.map((action) => [action.id, action])),
        touched: new Set<string>(),
      };

      for (const action of all) {
        if (action.status !== 'pending') continue;

        const dependency = resolveDependency(action, context.byId);

        // Dependency belum selesai → tunggu (urut `ts`), item sesudahnya tetap pending.
        if (dependency === 'pending') break;

        // Dependency gagal → tandai failed & LEWATI, jangan `break` (queue tidak boleh stuck).
        if (dependency === 'failed') {
          const kept = await keepAction(
            action,
            { status: 'failed', error: `dependency_failed:${action.depends_on ?? 'unknown'}` },
            context
          );
          result.skipped.push(
            buildOutcome(kept, { status: 0, reason: 'dependency_failed', kept: true })
          );
          continue;
        }

        result.processed += 1;
        await keepAction(action, { status: 'flushing' }, context);

        const resolved = await submit(action, context);

        if (resolved.bucket === 'succeeded') result.succeeded.push(resolved.outcome);
        else if (resolved.bucket === 'conflicted') result.conflicted.push(resolved.outcome);
        else if (resolved.bucket === 'skipped') result.skipped.push(resolved.outcome);
        else result.failed.push(resolved.outcome);
      }

      result.touchedResources = [...context.touched];
      result.pendingAfter = await database.count(STORE);
      config.onFlushComplete?.(result);
      return result;
    }

    return {
      async enqueue(input: EnqueueInput): Promise<string> {
        const database = await db();

        // `ts` dibuat MONOTON NAIK. Kalau dua aksi di-enqueue dalam milidetik yang sama,
        // urutan baca IndexedDB bisa acak → dependency `pending` salah terdeteksi → queue
        // berhenti prematur (`break`). Dengan ts unik & naik, urutan selalu = urutan enqueue.
        const existing = await database.getAll(STORE);
        const maxTs = existing.reduce((max, action) => Math.max(max, action.ts), 0);

        const action: OfflineAction = {
          ...input,
          id: generateUUID(),
          ts: Math.max(Date.now(), maxTs + 1),
          status: 'pending',
          // Dibuat SEKALI di sini → retry tidak pernah menduplikasi aksi di server (§12.3).
          idempotency_key: generateUUID(),
        };

        await database.put(STORE, action);
        return action.id;
      },
      async size(): Promise<number> {
        const database = await db();
        return await database.count(STORE);
      },
      async list(): Promise<OfflineAction[]> {
        return await readAll();
      },
      async get(id: string): Promise<OfflineAction | undefined> {
        const database = await db();
        return await database.get(STORE, id);
      },
      async remove(id: string): Promise<void> {
        const database = await db();
        await database.delete(STORE, id);
      },
      async clear(): Promise<void> {
        const database = await db();
        await database.clear(STORE);
      },
      flush,
    };
  }
