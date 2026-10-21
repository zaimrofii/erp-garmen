import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import {
  chatErrorMessage,
  minimalContext,
  validateContextForSubmit,
} from '@/lib/ai-context';
import type { AIChatContext } from '@/types/ai-chat';

/**
 * Sprint E.5 — pre-validasi konteks & fallback `forbidden_context` di `/ai/chat`.
 * Handler form tidak dijalankan (tanpa jsdom); logika validasi diuji PURE dan
 * wiring diverifikasi dari SUMBER halaman (pola repo).
 */

const ROOT = path.resolve(import.meta.dirname, '../../..');
const PAGE = readFileSync(path.join(ROOT, 'src/pages/ai/AIChatPage.tsx'), 'utf8');

const INVALID_DETAIL: AIChatContext = {
  page_type: 'detail',
  route: '/master/products',
  resource_type: 'product',
  resource_id: null,
  filters: {},
  visible_fields_snapshot: {},
};

const LIST_CONTEXT: AIChatContext = {
  page_type: 'list',
  route: '/master/products',
  resource_type: 'product',
  resource_id: null,
  filters: { search: 'kaos' },
  visible_fields_snapshot: {},
};

const VALID_DETAIL: AIChatContext = {
  ...INVALID_DETAIL,
  route: '/master/products/1',
  resource_id: '1',
};

function noticeFor(context: AIChatContext): string | null {
  const validation = validateContextForSubmit(context);
  return validation.ok
    ? null
    : `Konteks tidak valid: ${validation.reason ?? 'periksa halaman aktif'}`;
}

describe('Sprint E.5 — pre-validasi halaman chat', () => {
  it('konteks invalid → pesan tampil & request TIDAK dikirim', () => {
    const notice = noticeFor(INVALID_DETAIL);

    expect(notice).toContain('Konteks tidak valid');
    // Halaman berhenti sebelum sendMessage saat notice terisi.
    expect(PAGE).toMatch(/if \(!validation\.ok\) \{[\s\S]{0,160}return;/);
  });

  it('response forbidden_context → pesan benar', () => {
    expect(chatErrorMessage('forbidden_context')).toContain(
      'Anda tidak berhak melihat data konteks ini',
    );
  });

  it('tombol "Kirim tanpa konteks" memakai konteks minimal', () => {
    expect(PAGE).toContain('retryWithoutContext(minimalContext(location.pathname))');
    expect(PAGE).toContain('Kirim tanpa konteks');

    const request = minimalContext('/master/products/1');
    expect(request).toMatchObject({
      page_type: null,
      resource_type: null,
      resource_id: null,
    });
  });

  it('list exempt (resource_type tanpa id) → lolos pre-validasi', () => {
    expect(validateContextForSubmit(LIST_CONTEXT)).toEqual({ ok: true });
  });

  it('form new (resource_type terisi, id null) → ditolak', () => {
    const result = validateContextForSubmit({ ...INVALID_DETAIL, page_type: 'form' });

    expect(result.ok).toBe(false);
  });

  it('detail valid → boleh dikirim', () => {
    expect(validateContextForSubmit(VALID_DETAIL)).toEqual({ ok: true });
    expect(PAGE).toMatch(/chat\.sendMessage\(message, context, ["']DESKTOP["']\)/);
  });
});
