import { readFileSync } from 'node:fs';
import path from 'node:path';
import { createElement, type ReactElement } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { WorkOrderListPage } from '@/pages/work-orders/WorkOrderListPage';
import { attrsOf, htmlOf, textOf } from '../../helpers/react-tree';

/**
 * FASE K3 - halaman Work Order `/work-orders`: mode KANBAN di halaman lama (tanpa route
 * baru), preferensi `localStorage['mes-view-work-orders']`.
 *
 * Pindah kartu = `runWorkOrderCrudAction` (aksi state machine H2.3) dan `action_id`
 * backend WAJIB lolos gerbang `WORK_ORDER_ACTIONS` - aksi di luar union FE ditolak
 * sebelum menyentuh server.
 */

const ROOT = path.resolve(import.meta.dirname, '../../..');

function read(relative: string): string {
  return readFileSync(path.join(ROOT, relative), 'utf8');
}

const PAGE = read('src/pages/work-orders/WorkOrderListPage.tsx');
const APP = read('src/App.tsx');

function stubStorage(value: string | null): void {
  vi.stubGlobal('localStorage', { getItem: () => value, setItem: () => undefined });
}

function renderPage(): ReactElement {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });

  return createElement(
    QueryClientProvider,
    { client },
    createElement(
      MemoryRouter,
      { initialEntries: ['/work-orders'] },
      createElement(
        Routes,
        null,
        createElement(Route, { path: '/work-orders', element: createElement(WorkOrderListPage) }),
      ),
    ),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('FASE K3 - WorkOrderListPage: mode tampilan', () => {
  it('tanpa preferensi tersimpan: mode `list` aktif', () => {
    const tree = renderPage();

    expect(textOf(tree)).toContain('Work Order');
    expect(attrsOf(tree, 'aria-pressed')).toEqual(['true', 'false']);
    expect(htmlOf(tree)).not.toContain('data-kanban-columns');
  });

  it('preferensi `kanban`: papan dipilih (toggle Kanban aktif)', () => {
    stubStorage('kanban');

    const tree = renderPage();

    // PRA-0A.1 (K3) — MODES = ["kanban","list"]: mode pertama (kanban) aktif.
    expect(attrsOf(tree, 'aria-pressed')).toEqual(['true', 'false']);
    expect(htmlOf(tree)).not.toContain('<ul');
  });

  it('wiring kanban: hook K2 WO + endpoint kanban + aksi state machine', () => {
    expect(PAGE).toMatch(
      /import \{\s*useWorkOrdersKanban,\s*workOrdersKanbanQueryKey,?\s*\} from "@\/hooks\/useWorkOrdersKanban"/,
    );
    expect(PAGE).toContain('storageKey={VIEW_STORAGE_KEYS.workOrders}');
    expect(PAGE).toContain('useWorkOrdersKanban(KANBAN_PARAMS, isKanban)');
    expect(PAGE).toContain('WORK_ORDER_ACTIONS');
    expect(PAGE).toContain('runWorkOrderCrudAction(client, cardId, toWorkOrderAction(actionId))');
    expect(PAGE).toContain('queryKey: workOrdersKanbanQueryKey(KANBAN_PARAMS)');
    expect(PAGE).toContain("Aksi '${actionId}' tidak dikenal untuk Work Order.");
  });

  it('kontrak F13 WO tetap utuh + TANPA route baru (mode toggle)', () => {
    expect(PAGE).toContain('import { useWorkOrders } from "@/hooks/useWorkOrders"');
    expect(PAGE).toContain('Muat lebih banyak');
    expect(PAGE).toContain('/production/work-orders/new');
    expect(APP).toContain('path="/work-orders"');
    expect(APP).not.toContain('path="/work-orders/kanban');
  });

  it('detail kartu & toast error: klik kartu ke halaman detail, invalid = toast', () => {
    expect(PAGE).toContain('navigate(`/production/work-orders/${String(card.id)}`)');
    expect(PAGE).toContain('onInvalidMove={(invalid) => {');
    expect(PAGE).toContain('title="Perpindahan tidak valid"');
    expect(PAGE).toContain('onErrorMessage: (message) => setMoveError(message)');
    expect(PAGE).not.toContain('setQueryData');
  });
});
