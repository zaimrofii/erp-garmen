import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

/**
 * F11/11.1 — halaman form scrap (`/production/scrap/:id`).
 *
 * Rendering penuh butuh Router + QueryClient + provider runtime (tanpa DOM), jadi tes ini
 * memaku wiring sumber: form → `submitBundleAction` (POST `/garmen/bundles/{id}/BUNDLE_SCRAP/`),
 * guard 4 lapis (qty, alasan, metadata `allowed_actions`, state state-machine), konfirmasi,
 * dan feedback (Toast + trigger). Id aksi TIDAK boleh di-hardcode sebagai slug.
 */

const ROOT = path.resolve(import.meta.dirname, '../../..');

function read(relative: string): string {
  return readFileSync(path.join(ROOT, relative), 'utf8');
}

const PAGE = 'src/pages/production/ScrapFormPage.tsx';

describe('F11/11.4a — route', () => {
  const app = read('src/App.tsx');

  it('route /production/scrap/:id + guard PRODUCTION + lazy chunk', () => {
    expect(app).toContain('path="/production/scrap/:id"');
    expect(app).toContain('<ScrapFormPage />');
    expect(app).toMatch(/path="\/production\/scrap\/:id"[\s\S]{0,160}PRODUCTION_ROLES/);
    expect(app).toContain("import('@/pages/production/ScrapFormPage')");
  });
});

describe('F11/11.1a-11.1b — form + submit', () => {
  const page = read(PAGE);

  it('submit lewat submitBundleAction dengan id aksi dari konstanta (bukan slug)', () => {
    expect(page).toContain("import { submitBundleAction } from '@/api/bundles'");
    expect(page).toContain('submitBundleAction(');
    expect(page).toContain('BUNDLE_ACTION_IDS.SCRAP');
    expect(page).not.toContain("'BUNDLE_SCRAP'");
    expect(page).not.toContain("'/bundle-scrap/'");
  });

  it('idempotency key + optimistic lock (X-Base-Version) ikut dikirim', () => {
    expect(page).toContain('idempotencyKey: generateUUID()');
    expect(page).toContain('baseVersion: bundle.version');
  });

  it('payload memuat qty + reason (dokumentasi: qty/reason = catatan operator)', () => {
    expect(page).toContain('scrap_qty: qty');
    expect(page).toContain('reason: reason.trim()');
    expect(page).toContain('EXTRA_CRITICAL_FIELDS');
  });

  it('form punya input qty + textarea alasan + modal konfirmasi', () => {
    expect(page).toContain('Qty scrap (pcs)');
    expect(page).toContain('Alasan scrap');
    expect(page).toContain('<Modal');
    expect(page).toContain('Konfirmasi SCRAP');
    // Kontrol memakai atom yang SUDAH punya label sendiri (Input/Textarea) - sesuai
    // docstring `FormField` yang hanya untuk kontrol tanpa label.
    expect(page).toContain('<Input');
    expect(page).toContain('<Textarea');
  });
});

describe('F11/11.1c-11.1d — feedback + guard', () => {
  const page = read(PAGE);

  it('feedback: trigger success/error + Toast', () => {
    expect(page).toContain("trigger('success')");
    expect(page).toContain("trigger('error')");
    expect(page).toContain('<Toast');
  });

  it('guard qty: bilangan ≥ 1 dan ≤ qty bundle', () => {
    expect(page).toContain('parseScrapQty');
    expect(page).toContain('parsed >= 1 ? parsed : null');
    expect(page).toContain('Maksimal ${String(bundleQty)} pcs (qty bundle).');
  });

  it('guard alasan minimal 3 karakter', () => {
    expect(page).toContain('MIN_REASON_LENGTH = 3');
    expect(page).toContain('Alasan minimal ${String(MIN_REASON_LENGTH)} karakter.');
  });

  it('guard metadata allowed_actions + state state-machine', () => {
    expect(page).toContain('hasAllowedAction(allowedActions, BUNDLE_ACTION_IDS.SCRAP)');
    expect(page).toContain('canRunBundleAction(BUNDLE_ACTION_IDS.SCRAP, bundle?.state)');
    expect(page).toContain('disabled={!canSubmit}');
    expect(page).toContain('role="alert"');
  });

  it('error handling: pesan dari Error (mis. 400/409) ditampilkan, tidak ditelan', () => {
    expect(page).toContain('caught instanceof Error ? caught.message');
    expect(page).toContain('title: \'Scrap gagal\'');
  });
});
