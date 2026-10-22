import { readFileSync } from 'node:fs';
import path from 'node:path';
import { createElement } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { HitlQueuePage } from '@/pages/ai/HitlQueuePage';
import { htmlOf } from '../../helpers/react-tree';
import type { HitlQueuePage as HitlPage } from '@/types/hitl-queue';

/**
 * Fix #19A — HITL modal: callback harus stabil agar parent re-render
 * (setiap ketikan) tidak memicu ulang focus effect Modal.
 */

const SRC = readFileSync(
  path.resolve(import.meta.dirname, '../../../src/pages/ai/HitlQueuePage.tsx'),
  'utf8',
);

const PAGE: HitlPage = {
  rows: [
    {
      id: 1,
      decision_log_id: 1,
      risk_level: 'MEDIUM',
      proposed_action: { actions: [{ action: 'rework BND-1' }] },
      required_approver_role: 'SUPERVISOR',
      channel: 'WA',
      status: 'PENDING',
      query_text: 'apa yang harus saya lakukan?',
      intent: 'SUGGEST_ACTION',
      confidence_score: 0.8,
      expires_at: null,
      created_at: '2026-10-21T08:00:00Z',
      decided_by: null,
      decided_at: null,
      rejection_reason: '',
    },
  ],
  total_count: 1,
  has_more: false,
  next_cursor: null,
};

function renderPage(): string {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return htmlOf(
    createElement(
      QueryClientProvider,
      { client },
      createElement(
        MemoryRouter,
        { initialEntries: ['/ai/hitl'] },
        createElement(HitlQueuePage, { initialPage: PAGE }),
      ),
    ),
  );
}

describe('Fix #19A — HitlQueuePage modal stabil', () => {
  it('closeModal dibungkus useCallback dengan deps kosong', () => {
    expect(SRC).toMatch(/const closeModal = useCallback\([\s\S]{0,200}\}, \[\]\);/);
  });

  it('handleOpenChange stabil dan bergantung pada closeModal', () => {
    expect(SRC).toMatch(
      /const handleOpenChange = useCallback\([\s\S]{0,160}\[closeModal\],/,
    );
  });

  it('Modal memakai handler stabil (bukan arrow inline)', () => {
    expect(SRC).toContain('onOpenChange={handleOpenChange}');
    expect(SRC).not.toContain('onOpenChange={(open)');
  });

  it('textarea modal tidak punya key dinamis', () => {
    const modal = SRC.slice(SRC.indexOf('<Modal'), SRC.indexOf('</Modal>'));
    expect(modal).toContain('aria-label="Catatan persetujuan"');
    expect(modal).toContain('aria-label="Alasan penolakan"');
    expect(modal).not.toMatch(/\bkey=/);
  });

  it('halaman tetap merender tabel + filter', () => {
    const html = renderPage();

    expect(html).toContain('Antrean Persetujuan AI');
    expect(html).toContain('rework BND-1');
    expect(html).toContain('aria-label="Filter status"');
  });
});
