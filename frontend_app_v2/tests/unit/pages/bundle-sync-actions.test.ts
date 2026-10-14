import { afterEach, describe, expect, it, vi } from 'vitest';
import { SyncActionsCard } from '@/components/molecules/SyncActionsCard';
import { createApiClient } from '@/integrations/api-client';
import {
  buildBundleSyncInput,
  canSyncFg,
  canSyncScrap,
  canSyncWip,
  runBundleStageSync,
} from '@/lib/sync-actions';
import { callProp, findElement } from '../../helpers/react-tree';

/**
 * F6 — tombol sync WIP/FG di halaman bundle.
 *
 * Tanpa DOM (jsdom tidak jalan di bun):
 *  - guard state & body diuji lewat helper murni `lib/sync-actions.ts`;
 *  - `postSyncOdoo` dipanggil dengan stage & URL benar → diuji lewat
 *    `runBundleStageSync` + `createApiClient` (fetch di-stub);
 *  - klik tombol → callback halaman: `SyncActionsCard` tanpa hook, jadi pohon
 *    element-nya bisa di-walk dan `onClick`-nya dipanggil.
 */

const BUNDLE = { id: 16, code: 'BND-00016', qty: 4 };

function stubFetch(status = 200): { calls: { url: string; init: RequestInit }[] } {
  const calls: { url: string; init: RequestInit }[] = [];

  vi.stubGlobal(
    'fetch',
    vi.fn((url: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ url: String(url), init: init ?? {} });

      const body = {
        ok: true,
        status: 'queued',
        task_id: 'task-1',
        sync_record_id: 15,
        stage: 'WIP',
        resource: 'bundle',
        resource_id: '16',
      };

      return Promise.resolve(
        new Response(JSON.stringify(status === 200 ? body : { detail: 'Autentikasi diperlukan.' }), {
          status,
          headers: { 'Content-Type': 'application/json' },
        }),
      );
    }),
  );

  return { calls };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

function buttonWithLabel(tree: unknown, label: string) {
  return findElement(tree as never, (element) => element.props['children'] === label);
}

function renderCard(overrides: Partial<Parameters<typeof SyncActionsCard>[0]> = {}) {
  const onSync = vi.fn();
  const onPrintCoupon = vi.fn();
  const onTicketCodeChange = vi.fn();

  const props: Parameters<typeof SyncActionsCard>[0] = {
    state: 'CUTTING',
    syncBusy: null,
    couponBusy: false,
    ticketCode: '',
    onTicketCodeChange,
    onSync,
    onPrintCoupon,
    ...overrides,
  };

  return { onSync, onPrintCoupon, onTicketCodeChange, tree: SyncActionsCard(props) };
}

describe('F6/6.6 — guard state bundle', () => {
  it('WIP aktif untuk CUTTING/SEWING/QC saja', () => {
    for (const state of ['CUTTING', 'SEWING', 'QC', 'cutting']) {
      expect(canSyncWip(state), state).toBe(true);
    }

    for (const state of ['DRAFT', 'DONE', 'SCRAPPED', '']) {
      expect(canSyncWip(state), state).toBe(false);
    }
  });

  it('FG hanya untuk DONE', () => {
    expect(canSyncFg('DONE')).toBe(true);
    expect(canSyncFg('done')).toBe(true);
    expect(canSyncFg('QC')).toBe(false);
  });

  it('scrap hanya untuk QC', () => {
    expect(canSyncScrap('QC')).toBe(true);
    expect(canSyncScrap('DONE')).toBe(false);
  });
});

describe('F6/6.1-6.2 — body & pemanggilan postSyncOdoo', () => {
  it('body kontrak §5.1: resource/resource_id/payload{qty,ref}', () => {
    expect(buildBundleSyncInput(BUNDLE, 'WIP')).toEqual({
      resource: 'bundle',
      resource_id: '16',
      payload: { qty: 4, ref: 'WIP-BND-00016' },
    });
    expect(buildBundleSyncInput(BUNDLE, 'FG').payload).toEqual({ qty: 4, ref: 'FG-BND-00016' });
  });

  it('stage WIP → POST /api/v1/sync/odoo/WIP/ (credentials include + body benar)', async () => {
    const { calls } = stubFetch(200);
    const client = createApiClient({ baseUrl: 'http://localhost:8000/api/v1' });

    const outcome = await runBundleStageSync(client, 'WIP', BUNDLE);

    expect(calls[0]?.url).toBe('http://localhost:8000/api/v1/sync/odoo/WIP/');
    expect(calls[0]?.init.method).toBe('POST');
    expect(calls[0]?.init.credentials).toBe('include');
    expect(JSON.parse(String(calls[0]?.init.body))).toEqual({
      resource: 'bundle',
      resource_id: '16',
      payload: { qty: 4, ref: 'WIP-BND-00016' },
    });
    expect(outcome.ok).toBe(true);
    expect(outcome.message).toContain('task-1');
  });

  it('stage FG → POST /api/v1/sync/odoo/FG/', async () => {
    const { calls } = stubFetch(200);
    const client = createApiClient({ baseUrl: 'http://localhost:8000/api/v1' });

    await runBundleStageSync(client, 'FG', BUNDLE);

    expect(calls[0]?.url).toBe('http://localhost:8000/api/v1/sync/odoo/FG/');
  });

  it('403 (tanpa session) → union gagal, TIDAK throw', async () => {
    stubFetch(403);
    const client = createApiClient({ baseUrl: 'http://localhost:8000/api/v1' });

    const outcome = await runBundleStageSync(client, 'WIP', BUNDLE);

    expect(outcome.ok).toBe(false);
    // F6.2: `api-client` kini membaca `detail` DRF (sebelumnya hanya `HTTP <status>`),
    // jadi pesan backend ("Autentikasi diperlukan.") yang tampil ke user.
    expect(outcome.message).toContain('Autentikasi diperlukan.');
  });
});

describe('F6 — SyncActionsCard (render + klik)', () => {
  it('state DRAFT: tombol WIP & FG disabled, klik tidak memicu apa pun', () => {
    const { tree, onSync } = renderCard({ state: 'DRAFT' });

    const wip = buttonWithLabel(tree, 'Sync WIP');
    const fg = buttonWithLabel(tree, 'Sync FG');

    expect(wip?.props['disabled']).toBe(true);
    expect(fg?.props['disabled']).toBe(true);

    callProp(wip!, 'onClick');
    expect(onSync).not.toHaveBeenCalled();
  });

  it('state CUTTING: WIP aktif → klik memanggil onSync("WIP")', () => {
    const { tree, onSync } = renderCard({ state: 'CUTTING' });

    const wip = buttonWithLabel(tree, 'Sync WIP');
    expect(wip?.props['disabled']).toBe(false);

    callProp(wip!, 'onClick');
    expect(onSync).toHaveBeenCalledWith('WIP');
  });

  it('state DONE: FG aktif → klik memanggil onSync("FG"), WIP disabled', () => {
    const { tree, onSync } = renderCard({ state: 'DONE' });

    expect(buttonWithLabel(tree, 'Sync WIP')?.props['disabled']).toBe(true);

    callProp(buttonWithLabel(tree, 'Sync FG')!, 'onClick');
    expect(onSync).toHaveBeenCalledWith('FG');
  });

  it('sedang sync (syncBusy) → kedua tombol terkunci', () => {
    const { tree } = renderCard({ state: 'CUTTING', syncBusy: 'WIP' });

    expect(buttonWithLabel(tree, 'Sync WIP')?.props['disabled']).toBe(true);
    expect(buttonWithLabel(tree, 'Sync FG')?.props['disabled']).toBe(true);
  });

  it('kupon: disabled kalau ticket code kosong; aktif & klik setelah diisi', () => {
    const empty = renderCard({ state: 'CUTTING', ticketCode: '   ' });
    expect(buttonWithLabel(empty.tree, 'Cetak Kupon')?.props['disabled']).toBe(true);

    const filled = renderCard({ state: 'CUTTING', ticketCode: 'TKT-001' });
    const coupon = buttonWithLabel(filled.tree, 'Cetak Kupon');

    expect(coupon?.props['disabled']).toBe(false);
    callProp(coupon!, 'onClick');
    expect(filled.onPrintCoupon).toHaveBeenCalledTimes(1);
  });

  it('input ticket code terkendali (label + value + placeholder)', () => {
    const { tree } = renderCard({ state: 'CUTTING', ticketCode: 'TKT-001' });
    const input = findElement(
      tree,
      (element) => element.props['label'] === 'Kode kupon (ticket_code)',
    );

    expect(input?.props['value']).toBe('TKT-001');
    expect(input?.props['placeholder']).toBe('mis. TKT-001');
  });
});
