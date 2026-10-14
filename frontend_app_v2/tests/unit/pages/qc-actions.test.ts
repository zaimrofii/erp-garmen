import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import {
  BUNDLE_ACTION_IDS,
  canRunBundleAction,
  canSubmitBundleAction,
  hasAllowedAction,
} from '@/lib/action-runner';

/**
 * F11/11.2 — aksi BUNDLE_QC + BUNDLE_SCRAP di QCPage.
 *
 * `BUNDLE_QC` (SEWING → QC) dan `BUNDLE_SCRAP` ({DRAFT,CUTTING,SEWING,QC} → DONE) berasal dari
 * seed state machine `garment.bundle`; tombol hanya aktif kalau id-nya ADA di `allowed_actions`
 * (metadata) DAN state sekarang sah.
 */

const ROOT = path.resolve(import.meta.dirname, '../../..');

function read(relative: string): string {
  return readFileSync(path.join(ROOT, relative), 'utf8');
}

const QC_PAGE = 'src/pages/production/QCPage.tsx';

describe('F11/11.3b — konstanta & guard aksi bundle', () => {
  it('id aksi apa adanya (bukan slug) + BUNDLE_QC/BUNDLE_SCRAP terdaftar', () => {
    expect(BUNDLE_ACTION_IDS.QC).toBe('BUNDLE_QC');
    expect(BUNDLE_ACTION_IDS.SCRAP).toBe('BUNDLE_SCRAP');
    expect(BUNDLE_ACTION_IDS.REWORK).toBe('BUNDLE_REWORK');
  });

  it('BUNDLE_QC hanya sah dari SEWING (docs §4.4)', () => {
    expect(canRunBundleAction(BUNDLE_ACTION_IDS.QC, 'SEWING')).toBe(true);
    expect(canRunBundleAction(BUNDLE_ACTION_IDS.QC, 'sewing')).toBe(true);
    expect(canRunBundleAction(BUNDLE_ACTION_IDS.QC, 'CUTTING')).toBe(false);
    expect(canRunBundleAction(BUNDLE_ACTION_IDS.QC, 'QC')).toBe(false);
    expect(canRunBundleAction(BUNDLE_ACTION_IDS.QC, 'DONE')).toBe(false);
  });

  it('BUNDLE_SCRAP sah dari semua state non-terminal, TIDAK dari DONE', () => {
    for (const state of ['DRAFT', 'CUTTING', 'SEWING', 'QC']) {
      expect(canRunBundleAction(BUNDLE_ACTION_IDS.SCRAP, state), state).toBe(true);
    }

    expect(canRunBundleAction(BUNDLE_ACTION_IDS.SCRAP, 'DONE')).toBe(false);
    expect(canRunBundleAction(BUNDLE_ACTION_IDS.SCRAP, '')).toBe(false);
    expect(canRunBundleAction(BUNDLE_ACTION_IDS.SCRAP, null)).toBe(false);
  });

  it('aksi tak dipetakan (BUNDLE_REWORK) → fail-closed di state guard', () => {
    expect(canRunBundleAction(BUNDLE_ACTION_IDS.REWORK, 'QC')).toBe(false);
  });

  it('hasAllowedAction + canSubmitBundleAction butuh metadata DAN state', () => {
    const allowed = [{ id: 'BUNDLE_QC' }];

    expect(hasAllowedAction(allowed, 'BUNDLE_QC')).toBe(true);
    expect(hasAllowedAction(allowed, 'BUNDLE_SCRAP')).toBe(false);
    expect(canSubmitBundleAction(allowed, 'BUNDLE_QC', 'SEWING')).toBe(true);
    // ada di metadata tapi state salah → tetap tidak boleh
    expect(canSubmitBundleAction(allowed, 'BUNDLE_QC', 'CUTTING')).toBe(false);
    // state benar tapi tidak di metadata → tetap tidak boleh
    expect(canSubmitBundleAction([], 'BUNDLE_QC', 'SEWING')).toBe(false);
  });
});

describe('F11/11.2a-11.2c — wiring QCPage', () => {
  const page = read(QC_PAGE);

  it('tombol LULUS QC memakai ActionButton variant qc', () => {
    expect(page).toContain('variant="qc"');
    expect(page).toContain('label="LULUS QC"');
    expect(page).toContain("setConfirmAction('BUNDLE_QC')");
    expect(page).toContain("pending === 'BUNDLE_QC'");
  });

  it('variant qc ada di ActionButton (ikon + tone + feedback)', () => {
    const button = read('src/components/molecules/ActionButton.tsx');

    expect(button).toContain("'start' | 'finish' | 'qc' | 'scrap' | 'rework'");
    expect(button).toContain('bg-accent-blue');
    expect(button).toContain("qc: { beep: 'success', haptic: 'success', flash: 'success' }");
  });

  it('guard state dua lapis dipakai untuk QC + SCRAP (bukan cek metadata saja)', () => {
    expect(page).toContain('canSubmitBundleAction(allowedActions, BUNDLE_ACTION_IDS.QC, bundle?.state)');
    expect(page).toContain('canSubmitBundleAction(allowedActions, BUNDLE_ACTION_IDS.SCRAP, bundle?.state)');
    expect(page).toContain('hasAllowedAction(allowedActions, BUNDLE_ACTION_IDS.REWORK)');
    expect(page).toContain('disabled={!canQc || busy}');
    expect(page).toContain('disabled={!canScrap || defects.isEmpty || busy}');
  });

  it('REWORK/SCRAP lama tetap ada; SUBMIT dummy TIDAK dipaksa ke endpoint 404', () => {
    expect(page).toContain('variant="rework"');
    expect(page).toContain('variant="scrap"');
    // SUBMIT masih catatan lokal (adapter dummy) - jangan di-remap ke endpoint yang tidak ada
    expect(page).toContain('submitQCRecord');
    expect(page).not.toContain('/quality/defects/');
  });

  it('F6 (sync scrap ke Odoo) tetap terpisah dari aksi state bundle', () => {
    expect(page).toContain('runScrapSync(client)');
    expect(page).toContain('BUNDLE_ACTION_IDS.SCRAP');
  });

  it('modal konfirmasi punya judul/tombol per aksi + jalan ke form scrap', () => {
    expect(page).toContain('CONFIRM_TITLE');
    expect(page).toContain('CONFIRM_BUTTON');
    expect(page).toContain('Isi Form Scrap');
    expect(page).toContain('`/production/scrap/${id ?? \'\'}`');
  });
});
