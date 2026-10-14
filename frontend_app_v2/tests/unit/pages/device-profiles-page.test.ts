import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { readDeviceBindingState } from '@/api/devices';
import { BindDeviceModal } from '@/components/molecules/BindDeviceModal';
import { readWcOptions } from '@/lib/device-mode';
import { attrOf, htmlOf, textOf } from '../../helpers/react-tree';

/**
 * F6.4 — halaman `/settings/devices`: bind/unbind device + status perangkat ini.
 *
 * Halaman butuh Router + QueryClient (di luar gaya tes tanpa DOM), jadi bagian ber-hook
 * diverifikasi lewat PEMERIKSAAN SUMBER, sementara bagian presentasional (modal) dan
 * pembacaan respons backend diuji langsung — pola yang sama seperti `devices-page.test.ts` (F7).
 *
 * CATATAN: daftar binding SEMUA perangkat belum bisa ditampilkan karena backend hanya punya
 * `GET /devices/me` (perangkat ini). Yang tampil = status perangkat INI secara akurat
 * (profil + WC + Bound/Unbound dari `source`), bukan tabel kosong/palsu.
 */

const ROOT = path.resolve(import.meta.dirname, '../../..');
const PAGE = readFileSync(path.join(ROOT, 'src/pages/settings/DeviceProfilesPage.tsx'), 'utf8');

describe('F6.4 — 8. status/binding tampil dari sumber nyata', () => {
  it('halaman membaca /devices/me via adapter (bukan fetch langsung)', () => {
    expect(PAGE).toContain("import { fetchMyDevice } from '@/api/devices'");
    expect(PAGE).toContain('fetchMyDevice(apiClient)');
    expect(PAGE).not.toContain('await fetch(');
    expect(PAGE).not.toContain('window.fetch');
  });

  it('baris profil + WC + status Bound/Unbound berasal dari `source`, bukan status code', () => {
    expect(PAGE).toContain('device.data?.profile');
    expect(PAGE).toContain('device.data?.wcCode');
    expect(PAGE).toContain('isBound');

    const bound = readDeviceBindingState({
      ok: true,
      status: 200,
      data: { device_profile: 'KIOS', confidence: 'high', source: 'device_binding', wc_code: 'SEW-01' },
    });
    const unbound = readDeviceBindingState({
      ok: true,
      status: 200,
      data: { device_profile: 'OPERATOR_HP', confidence: 'low', source: 'fallback', wc_code: null },
    });

    expect([bound.bound, bound.profile, bound.wcCode]).toEqual([true, 'KIOS', 'SEW-01']);
    expect(unbound.bound).toBe(false);
  });

  it('daftar WC untuk bind berasal dari laporan WIP per WC (B21) + opsi manual', () => {
    expect(PAGE).toContain('fetchWipByWc(apiClient)');
    expect(readWcOptions([{ wc_code: 'SEW-01' }, { wc_code: 'CUT-02' }, { wc_code: 'SEW-01' }])).toEqual([
      'CUT-02',
      'SEW-01',
    ]);
  });
});

describe('F6.4 — 9. Unbind selalu lewat konfirmasi', () => {
  it('tombol Unbind membuka modal konfirmasi (bukan langsung memanggil API)', () => {
    expect(PAGE).toContain('onClick={() => setConfirmUnbind(true)}');
    expect(PAGE).toContain('title="Cabut ikatan perangkat ini?"');
    expect(PAGE).toContain('<Button variant="danger" loading={unbind.isPending} onClick={() => unbind.mutate()}>');
  });

  it('setelah unbind (sukses ATAU gagal) → modal ditutup + status di-refresh', () => {
    expect(PAGE).toContain('setConfirmUnbind(false);');
    expect(PAGE).toContain('deviceProfileRefresh();');
  });
});

describe('F6.4 — 10. "Bind Device Baru" membuka modal', () => {
  it('tombol membuka modal & modal ter-render dengan data katalog', () => {
    expect(PAGE).toContain('Bind Device Baru');
    expect(PAGE).toContain('setBindOpen(true)');
    expect(PAGE).toContain('<BindDeviceModal');
    expect(PAGE).toContain('open={bindOpen}');
  });

  it('modal benar-benar tampil saat open=true (dialog + judulnya)', () => {
    const tree = BindDeviceModal({
      open: true,
      onOpenChange: () => undefined,
      profiles: [{ code: 'KIOS', label: 'Kios Lantai' }],
      wcOptions: ['SEW-01'],
      profile: 'KIOS',
      wcSelection: '',
      wcManual: '',
      busy: false,
      error: null,
      onProfileChange: () => undefined,
      onWcSelectionChange: () => undefined,
      onWcManualChange: () => undefined,
      onSubmit: () => undefined,
    });

    expect(attrOf(tree, 'role')).toBe('dialog');
    expect(textOf(tree)).toContain('Bind Device Baru');
    expect(htmlOf(tree)).toContain('KIOS — Kios Lantai');
  });
});
