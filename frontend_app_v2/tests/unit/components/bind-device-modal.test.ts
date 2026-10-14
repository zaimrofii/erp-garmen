import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it, vi } from 'vitest';
import { BindDeviceModal } from '@/components/molecules/BindDeviceModal';
import {
  MANUAL_WC_VALUE,
  NO_WC_VALUE,
  bindDeviceError,
  isManualWc,
  resolveWcCode,
  wcSelectOptions,
} from '@/lib/device-mode';
import { attrOf, attrsOf, callProp, findElement, htmlOf, textOf, walk } from '../../helpers/react-tree';

/**
 * F6.4 — `BindDeviceModal` (bind perangkat ini, `POST /devices/bind`).
 *
 * Modal bersifat CONTROLLED (state dimiliki halaman) sehingga bisa diuji tanpa DOM:
 * `renderToString` untuk struktur + `callProp` untuk handler. Alur sukses/gagal
 * (tutup modal + refresh resolver global) diverifikasi lewat sumber halaman.
 */

const ROOT = path.resolve(import.meta.dirname, '../../..');
const PAGE = readFileSync(path.join(ROOT, 'src/pages/settings/DeviceProfilesPage.tsx'), 'utf8');

const PROFILES = [
  { code: 'OPERATOR_HP', label: 'HP Operator' },
  { code: 'KIOS', label: 'Kios Lantai' },
];

function modal(overrides: Partial<Parameters<typeof BindDeviceModal>[0]> = {}) {
  return BindDeviceModal({
    open: true,
    onOpenChange: () => undefined,
    profiles: PROFILES,
    wcOptions: ['SEW-01', 'CUT-02'],
    profile: 'OPERATOR_HP',
    wcSelection: '',
    wcManual: '',
    busy: false,
    error: null,
    onProfileChange: () => undefined,
    onWcSelectionChange: () => undefined,
    onWcManualChange: () => undefined,
    onSubmit: () => undefined,
    ...overrides,
  });
}

describe('F6.4 — render modal bind', () => {
  it('menampilkan judul, dropdown profil & WC, dan tombol Bind', () => {
    const tree = modal();
    const text = textOf(tree);

    expect(text).toContain('Bind Device Baru');
    expect(text).toContain('Profil device');
    expect(text).toContain('Work center');
    expect(text).toContain('OPERATOR_HP — HP Operator');
    expect(text).toContain('(tanpa WC)');
    expect(text).toContain('Lainnya (isi manual)…');
    expect(attrOf(tree, 'data-bind-device-form')).toBe('true');
  });

  it('5. submit form valid → onSubmit dipanggil (tanpa error validasi)', () => {
    const onSubmit = vi.fn();
    const tree = modal({ onSubmit });
    // Tombol "Bind" ada di prop `footer` Modal (bukan children) → ditelusuri dari prop itu.
    const panel = findElement(tree as never, (element) => element.props['title'] === 'Bind Device Baru');
    let submit: Parameters<typeof callProp>[0] | undefined;
    walk(panel?.props['footer'] as never, (element) => {
      if (element.props['children'] === 'Bind') submit = element;
    });

    expect(attrsOf(tree, 'disabled')).toEqual([]); // tombol aktif
    expect(submit).toBeDefined();
    callProp(submit!, 'onClick');

    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(bindDeviceError({ profile: 'OPERATOR_HP' })).toBeNull();
  });

  it('6. submit tanpa profil → error validasi + tombol Bind non-aktif', () => {
    const onSubmit = vi.fn();
    const tree = modal({ profile: '', onSubmit });

    expect(bindDeviceError({ profile: '' })).toBe('Profil perangkat wajib dipilih.');
    expect(textOf(tree)).toContain('Profil perangkat wajib dipilih.');
    expect(attrsOf(tree, 'role')).toContain('alert');
    expect(attrsOf(tree, 'disabled').length).toBeGreaterThan(0); // tombol Bind non-aktif
  });

  it('error dari percobaan bind sebelumnya ditampilkan (role=alert)', () => {
    const tree = modal({ error: 'Profil perangkat tidak dikenal.' });

    expect(textOf(tree)).toContain('Profil perangkat tidak dikenal.');
  });

  it('busy → kedua tombol non-aktif (tidak bisa dobel submit)', () => {
    const tree = modal({ busy: true });

    expect(attrsOf(tree, 'disabled').length).toBeGreaterThanOrEqual(1);
  });
});

describe('F6.4 — WC dropdown + input manual', () => {
  it('opsi WC: "(tanpa WC)" + kode yang diketahui + opsi manual', () => {
    expect(wcSelectOptions(['SEW-01']).map((option) => option.value)).toEqual([
      NO_WC_VALUE,
      'SEW-01',
      MANUAL_WC_VALUE,
    ]);
    expect(isManualWc(MANUAL_WC_VALUE)).toBe(true);
    expect(isManualWc('SEW-01')).toBe(false);
  });

  it('resolveWcCode: dropdown dipakai apa adanya, manual → nilai input (trim)', () => {
    expect(resolveWcCode('SEW-01', 'diabaikan')).toBe('SEW-01');
    expect(resolveWcCode(NO_WC_VALUE, 'SEW-01')).toBe('');
    expect(resolveWcCode(MANUAL_WC_VALUE, '  WC-99  ')).toBe('WC-99');
  });

  it('input WC manual hanya muncul saat opsi manual dipilih', () => {
    const auto = htmlOf(modal({ wcSelection: 'SEW-01' }));
    const manual = htmlOf(modal({ wcSelection: MANUAL_WC_VALUE, wcManual: 'WC-99' }));

    expect(auto).not.toContain('Kode WC (manual)');
    expect(manual).toContain('Kode WC (manual)');
    // nilai input masuk ke HTML (atribut, bukan teks)
    expect(manual).toContain('value="WC-99"');
  });
});

describe('F6.4 — wiring halaman (7: sukses → tutup modal + refresh)', () => {
  it('bind sukses → setBindOpen(false) + refreshDeviceState(); gagal → setBindError', () => {
    expect(PAGE).toContain('setBindOpen(false)');
    expect(PAGE).toContain('setBindError(outcome.message)');
    expect(PAGE).toContain('refreshDeviceState();');
    expect(PAGE).toContain('deviceProfileRefresh();');
  });

  it('modal menerima profil dari katalog B28 + WC dari laporan WIP per WC (B21)', () => {
    expect(PAGE).toContain('profiles={profileRows.map((row) => ({ code: row.code, label: row.label }))}');
    expect(PAGE).toContain('wcOptions={wcOptions}');
    expect(PAGE).toContain('fetchWipByWc(apiClient)');
    expect(PAGE).toContain('readWcOptions(wipByWc.data?.rows ?? [])');
  });

  it('nama device tidak diminta: backend DeviceBinding tidak punya kolom nama', () => {
    expect(PAGE).not.toContain('Nama Device');
    // alasan dicatat di modal (satu tempat, tidak tersebar)
    const source = readFileSync(path.join(ROOT, 'src/components/molecules/BindDeviceModal.tsx'), 'utf8');
    expect(source).toContain('Nama Device TIDAK diminta');
  });
});
