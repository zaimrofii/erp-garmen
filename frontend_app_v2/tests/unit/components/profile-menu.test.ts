import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it, vi } from 'vitest';
import type { AuthUser } from '@/api/auth';
import { canOpenSettings, roleLabelFromCode, SETTINGS_ROLE_CODES } from '@/app/useRole';
import {
  ChangePasswordFields,
  ProfileMenuPanel,
  ProfileSummary,
} from '@/components/molecules/ProfileMenu';
import {
  displayNameOf,
  initialsOf,
  LOGIN_MESSAGES,
  LOGIN_PATH,
  passwordChangeError,
} from '@/lib/login-form';
import { attrOf, attrsOf, callProp, findElement, textOf } from '../../helpers/react-tree';

/**
 * F6.2 — menu profil di TopBar (`components/molecules/ProfileMenu.tsx`).
 *
 * Bagian presentasional diuji langsung (`renderToString` + `callProp`); bagian ber-hook
 * (buka menu, logout, modal) diverifikasi lewat pemeriksaan sumber — sama seperti tes
 * komponen lain di repo ini yang tidak memakai DOM/jsdom.
 */

const ROOT = path.resolve(import.meta.dirname, '../../..');

const ADMIN: AuthUser = {
  id: 7,
  username: 'admin1',
  email: 'admin1@klien.com',
  full_name: 'Admin Satu',
  role_code: 'ADMIN',
  is_superuser: false,
  is_staff: true,
};

describe('F6.2 — identitas user (pure)', () => {
  it('displayNameOf: full_name → username → "Belum login"', () => {
    expect(displayNameOf(ADMIN)).toBe('Admin Satu');
    expect(displayNameOf({ ...ADMIN, full_name: '' })).toBe('admin1');
    expect(displayNameOf(null)).toBe('Belum login');
  });

  it('initialsOf: maks. 2 huruf, kosong kalau tidak ada nama', () => {
    expect(initialsOf(ADMIN)).toBe('AS');
    expect(initialsOf({ ...ADMIN, full_name: '', username: 'operator1' })).toBe('O');
    expect(initialsOf(null)).toBe('');
  });
});

describe('F6.2 — ProfileSummary & panel menu', () => {
  it('menampilkan nama, email, dan LABEL role (read-only)', () => {
    const tree = ProfileSummary({ user: ADMIN });

    expect(attrOf(tree, 'data-profile-summary')).toBe('true');
    const text = textOf(tree);
    expect(text).toContain('Admin Satu');
    expect(text).toContain('admin1@klien.com');
    // FIX: label manusiawi dari `role_code` (dulu kode mentah "ADMIN")
    expect(text).toContain('Admin Sistem');
    expect(text).not.toContain('ADMIN');
  });

  it('tanpa email → tanda "—" (bukan baris kosong)', () => {
    expect(textOf(ProfileSummary({ user: { ...ADMIN, email: '' } }))).toContain('—');
    expect(textOf(ProfileSummary({ user: null }))).toContain('Belum login');
  });

  it('panel = role="menu" dengan 2 item (Ganti Password, Logout)', () => {
    const tree = ProfileMenuPanel({
      user: ADMIN,
      onSelectPassword: () => undefined,
      onSelectLogout: () => undefined,
    });

    expect(attrOf(tree, 'data-profile-menu')).toBe('true');
    expect(attrsOf(tree, 'role')).toEqual(['menu', 'menuitem', 'menuitem']);
    expect(textOf(tree)).toContain('Ganti Password');
    expect(textOf(tree)).toContain('Logout');
  });

  it('item menu memanggil callback yang diberikan', () => {
    const onSelectPassword = vi.fn();
    const onSelectLogout = vi.fn();
    const tree = ProfileMenuPanel({ user: ADMIN, onSelectPassword, onSelectLogout });
    const passwordItem = findElement(
      tree as never,
      (element) => element.props['onClick'] === onSelectPassword,
    );
    const logoutItem = findElement(
      tree as never,
      (element) => element.props['onClick'] === onSelectLogout,
    );

    callProp(passwordItem!, 'onClick');
    callProp(logoutItem!, 'onClick');

    expect(onSelectPassword).toHaveBeenCalledTimes(1);
    expect(onSelectLogout).toHaveBeenCalledTimes(1);
  });
});

describe('F6.2 — modal ganti password', () => {
  it('3 input password (lama/baru/konfirmasi)', () => {
    const tree = ChangePasswordFields({
      oldPassword: '',
      newPassword: '',
      confirmPassword: '',
      error: null,
      info: null,
      disabled: false,
      onOldPasswordChange: () => undefined,
      onNewPasswordChange: () => undefined,
      onConfirmPasswordChange: () => undefined,
    });

    expect(attrOf(tree, 'data-change-password')).toBe('true');
    expect(attrsOf(tree, 'type')).toEqual(['password', 'password', 'password']);
    expect(textOf(tree)).toContain('Password lama');
    expect(textOf(tree)).toContain('Konfirmasi password baru');
  });

  it('error → role="alert"; sukses → role="status"', () => {
    const base = {
      oldPassword: 'lama',
      newPassword: 'baru12345',
      confirmPassword: 'baru12345',
      disabled: false,
      onOldPasswordChange: () => undefined,
      onNewPasswordChange: () => undefined,
      onConfirmPasswordChange: () => undefined,
    };
    const failed = ChangePasswordFields({ ...base, error: 'Password lama salah', info: null });
    const success = ChangePasswordFields({
      ...base,
      error: null,
      info: LOGIN_MESSAGES.passwordChanged,
    });

    expect(attrOf(failed, 'role')).toBe('alert');
    expect(textOf(failed)).toContain('Password lama salah');
    expect(attrsOf(success, 'role')).toEqual(['status']);
    expect(textOf(success)).toContain(LOGIN_MESSAGES.passwordChanged);
  });

  it('passwordChangeError: lama kosong / <8 karakter / konfirmasi beda → ditolak', () => {
    expect(
      passwordChangeError({
        oldPassword: '',
        newPassword: 'rahasia456',
        confirmPassword: 'rahasia456',
      }),
    ).toBe(LOGIN_MESSAGES.missingOldPassword);
    expect(
      passwordChangeError({
        oldPassword: 'lama',
        newPassword: 'pendek',
        confirmPassword: 'pendek',
      }),
    ).toBe(LOGIN_MESSAGES.passwordTooShort);
    expect(
      passwordChangeError({
        oldPassword: 'lama',
        newPassword: 'rahasia456',
        confirmPassword: 'beda456',
      }),
    ).toBe(LOGIN_MESSAGES.passwordMismatch);
    expect(
      passwordChangeError({
        oldPassword: 'lama',
        newPassword: 'rahasia456',
        confirmPassword: 'rahasia456',
      }),
    ).toBeNull();
  });
});

describe('F6.2 — wiring TopBar ↔ ProfileMenu', () => {
  const topBar = readFileSync(path.join(ROOT, 'src/app/layouts/TopBar.tsx'), 'utf8');
  const menu = readFileSync(path.join(ROOT, 'src/components/molecules/ProfileMenu.tsx'), 'utf8');

  it('TopBar memakai user nyata (bukan DUMMY_USER) & signature tidak berubah', () => {
    expect(topBar).toContain('<ProfileMenu roleLabel={ROLE_LABELS[role]} />');
    expect(topBar).not.toContain('DUMMY_USER');
    expect(topBar).toContain('app: NavApp | undefined;');
    expect(topBar).toContain('onNavigate: (path: string) => void;');
  });

  it('trigger menu aksesibel (aria-haspopup/aria-expanded) dan punya nama', () => {
    expect(menu).toContain('aria-haspopup="menu"');
    expect(menu).toContain('aria-expanded={open}');
    expect(menu).toContain('aria-label="Menu akun"');
  });

  it('logout: panggil useAuth().logout() lalu redirect ke /login', () => {
    expect(menu).toContain('await logout()');
    expect(menu).toContain('navigate(LOGIN_PATH, { replace: true })');
    expect(LOGIN_PATH).toBe('/login');
  });

  it('ganti password: validasi klien → changePassword(old, new) → pesan sukses', () => {
    expect(menu).toContain('passwordChangeError({ oldPassword, newPassword, confirmPassword })');
    expect(menu).toContain('await changePassword(oldPassword, newPassword)');
    expect(menu).toContain('setInfo(LOGIN_MESSAGES.passwordChanged)');
  });

  it('modal ganti password memakai atom Modal + tombol Batal/Simpan', () => {
    expect(menu).toContain('<Modal');
    expect(menu).toContain('Batal');
    expect(menu).toContain('Simpan');
  });

  it('F6.4 — TopBar menampilkan badge device saat mode device (bukan menu akun)', () => {
    expect(topBar).toContain('useDeviceMode()');
    expect(topBar).toContain('data-device-badge="true"');
    expect(topBar).toContain('deviceBadgeLabel(device.profile, device.wcCode)');
    // menu akun tetap ada untuk mode session (bukan dihapus)
    expect(topBar).toContain('<ProfileMenu roleLabel={ROLE_LABELS[role]} />');
  });
});

describe('FIX — dropdown akun tidak ter-clip (mask ke lapisan dekoratif) + item Pengaturan', () => {
  const topBar = readFileSync(path.join(ROOT, 'src/app/layouts/TopBar.tsx'), 'utf8');
  const menu = readFileSync(path.join(ROOT, 'src/components/molecules/ProfileMenu.tsx'), 'utf8');

  it('TopBar: mask pindah ke lapisan dekoratif; <header> TIDAK ber-mask lagi', () => {
    const headerTag = /<header className="([^"]*)"/.exec(topBar)?.[1] ?? '';

    expect(headerTag.length).toBeGreaterThan(0);
    // mask di <header> memotong SEMUA descendant (mask-clip: border-box) = bug asli
    expect(headerTag).not.toContain('mask-image');
    // layer dekoratif tetap membawa mask yang sama supaya batas bawah header tetap lembut
    expect(topBar).toContain('aria-hidden="true"');
    expect(topBar).toContain('data-topbar-fade="true"');
    expect(topBar).toContain('pointer-events-none absolute inset-0 backdrop-blur');
    expect(topBar).toContain('[mask-image:linear-gradient(to_bottom,black_70%,transparent_100%)]');
  });

  it('roleLabelFromCode: kode → label manusiawi (bukan kode mentah)', () => {
    expect(roleLabelFromCode('OWNER')).toBe('Owner');
    expect(roleLabelFromCode('owner')).toBe('Owner');
    expect(roleLabelFromCode('ADMIN')).toBe('Admin Sistem');
    expect(roleLabelFromCode('OPERATOR')).toBe('Operator Lantai');
    expect(roleLabelFromCode('PURCHASING')).toBe('Staf Purchasing');
    expect(roleLabelFromCode('SABLON_LEAD')).toBe('SABLON_LEAD');
    expect(roleLabelFromCode(null)).toBe('—');
    expect(roleLabelFromCode('')).toBe('—');

    const owner: AuthUser = { ...ADMIN, role_code: 'OWNER' };
    const text = textOf(ProfileSummary({ user: owner }));

    expect(text).toContain('Owner');
    expect(text).not.toContain('OWNER');
    // `uppercase` dihapus dari chip: kalau masih ada, "Owner" akan tampil "OWNER" lagi
    expect(menu).not.toContain('uppercase');
  });

  it('canOpenSettings: hanya ADMIN/OWNER (dari role_code otoritatif, bukan useRole)', () => {
    expect(canOpenSettings('ADMIN')).toBe(true);
    expect(canOpenSettings('OWNER')).toBe(true);
    expect(canOpenSettings('owner')).toBe(true);
    expect(canOpenSettings('OPERATOR')).toBe(false);
    expect(canOpenSettings('QC')).toBe(false);
    expect(canOpenSettings('SUPERVISOR')).toBe(false);
    expect(canOpenSettings('PURCHASING')).toBe(false);
    expect(canOpenSettings(null)).toBe(false);
    expect(canOpenSettings('')).toBe(false);
  });

  it('SETTINGS_ROLE_CODES = cermin UPPERCASE dari SETTINGS_ROLES di App.tsx (anti-drift)', () => {
    const app = readFileSync(path.join(ROOT, 'src/App.tsx'), 'utf8');
    const raw = /const SETTINGS_ROLES: Role\[\] = \[([^\]]*)\]/.exec(app)?.[1] ?? '';
    const codes = raw
      .split(',')
      .map((part) => part.trim().replace(/^'|'$/g, '').toUpperCase())
      .filter((part) => part.length > 0);

    expect(codes.length).toBeGreaterThan(0);
    expect([...codes].sort()).toEqual([...SETTINGS_ROLE_CODES].sort());
  });

  it('panel: item Pengaturan muncul HANYA kalau handler-nya diberikan', () => {
    const base = {
      user: ADMIN,
      onSelectPassword: () => undefined,
      onSelectLogout: () => undefined,
    };

    const withSettings = ProfileMenuPanel({ ...base, onSelectSettings: () => undefined });
    const withoutSettings = ProfileMenuPanel(base);

    expect(attrsOf(withSettings, 'role')).toEqual(['menu', 'menuitem', 'menuitem', 'menuitem']);
    expect(attrOf(withSettings, 'data-profile-settings')).toBe('true');
    expect(textOf(withSettings)).toContain('Pengaturan');

    expect(attrsOf(withoutSettings, 'role')).toEqual(['menu', 'menuitem', 'menuitem']);
    expect(attrOf(withoutSettings, 'data-profile-settings')).toBeUndefined();
    expect(textOf(withoutSettings)).not.toContain('Pengaturan');
  });

  it('klik item Pengaturan memanggil handler → ProfileMenu navigate("/settings")', () => {
    const onSelectSettings = vi.fn();
    const tree = ProfileMenuPanel({
      user: ADMIN,
      onSelectPassword: () => undefined,
      onSelectLogout: () => undefined,
      onSelectSettings,
    });
    const item = findElement(
      tree as never,
      (element) => element.props['onClick'] === onSelectSettings,
    );

    callProp(item!, 'onClick');

    expect(onSelectSettings).toHaveBeenCalledTimes(1);
    // wiring nyata (bagian ber-hook): guard pakai role_code + navigasi ke /settings
    expect(menu).toContain('canOpenSettings(user?.role_code)');
    expect(menu).toContain("navigate('/settings')");
  });
});

