import { readFileSync } from 'node:fs';
import path from 'node:path';
import { createElement } from 'react';
import { describe, expect, it } from 'vitest';
import { Modal } from '@/components/atoms/Modal';
import { htmlOf } from '../../helpers/react-tree';

/**
 * Fix #19 — kontrak Modal: effect fokus TIDAK boleh bergantung pada callback
 * parent (inline), karena setiap ketikan membuat callback baru dan dulu
 * memindahkan fokus ke tombol Tutup. Perilaku fokus nyata diverifikasi di
 * jsdom (manual run); test ini mengunci struktur dependency-nya.
 */

const SRC = readFileSync(
  path.resolve(import.meta.dirname, '../../../src/components/atoms/Modal.tsx'),
  'utf8',
);
const FOCUS_EFFECT = SRC.slice(SRC.indexOf('Effect 1'), SRC.indexOf('Effect 2'));
const LISTENER_EFFECT = SRC.slice(SRC.indexOf('Effect 2'));

describe('Fix #19A — Modal tidak merebut fokus saat parent re-render', () => {
  it('effect fokus hanya bergantung pada [open]', () => {
    expect(FOCUS_EFFECT).toContain('}, [open]);');
    expect(FOCUS_EFFECT).not.toContain('onOpenChange');
  });

  it('listener ESC memakai ref, bukan prop langsung', () => {
    expect(LISTENER_EFFECT).toContain('onOpenChangeRef.current(false)');
    expect(LISTENER_EFFECT).toContain('}, [open]);');
  });

  it('restore fokus hanya ada di cleanup effect fokus', () => {
    expect(FOCUS_EFFECT).toContain('previouslyFocused?.focus()');
    expect(SRC.match(/previouslyFocused\?\.focus\(\)/g)).toHaveLength(1);
  });

  it('focus trap Tab + ESC tetap dipertahankan', () => {
    expect(SRC).toContain("event.key === 'Escape'");
    expect(SRC).toContain("event.key !== 'Tab'");
    expect(SRC).toContain('focusables[0].focus()');
  });

  it('modal terbuka tetap role=dialog + aria-modal', () => {
    const html = htmlOf(
      createElement(
        Modal,
        { open: true, onOpenChange: () => {}, title: 'Uji' },
        createElement('textarea', { 'aria-label': 'catatan' }),
      ),
    );

    expect(html).toContain('role="dialog"');
    expect(html).toContain('aria-modal="true"');
  });

  it('modal tertutup tidak merender dialog', () => {
    const html = htmlOf(
      createElement(Modal, { open: false, onOpenChange: () => {}, title: 'Uji' }),
    );

    expect(html).toBe('');
  });
});
