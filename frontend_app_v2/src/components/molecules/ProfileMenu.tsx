import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ChevronDown, KeyRound, LogOut, UserRound } from 'lucide-react';
import type { AuthUser } from '@/api/auth';
import { Button } from '@/components/atoms/Button';
import { Input } from '@/components/atoms/Input';
import { Modal } from '@/components/atoms/Modal';
import { useAuth } from '@/hooks/auth-context';
import { cn } from '@/lib/cn';
import {
  displayNameOf,
  errorMessageOf,
  initialsOf,
  LOGIN_MESSAGES,
  LOGIN_PATH,
  passwordChangeError,
} from '@/lib/login-form';
import { PILL } from '@/lib/tokens';

/**
 * ProfileMenu.tsx — pill user di TopBar (F6.2): avatar + nama + label role, membuka menu
 * berisi identitas user (read-only), "Ganti Password", dan "Logout".
 *
 * Kenapa bukan atom `Dropdown`: menu ini butuh blok kaya (nama + email + chip role) di
 * dalam panel, sementara `Dropdown` hanya menerima daftar item (label + ikon). Perilaku
 * a11y tetap sama: trigger `aria-haspopup="menu"`/`aria-expanded`, panel `role="menu"`
 * dengan item `role="menuitem"`, `Escape`/klik-luar menutup.
 *
 * Bagian presentasional (`ProfileSummary`, `ProfileMenuPanel`, `ChangePasswordFields`)
 * dipisah agar bisa diuji tanpa DOM (`tests/unit/components/profile-menu.test.ts`).
 */

const MENU_ITEM =
  'flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm font-medium text-foreground hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring';

/** Identitas user di dalam menu (read-only). */
export function ProfileSummary({ user }: { user: AuthUser | null }) {
  const email = user?.email ?? '';

  return (
    <div data-profile-summary="true" className="flex flex-col gap-0.5">
      <p className="text-sm font-semibold tracking-tight text-foreground">
        {displayNameOf(user)}
      </p>
      <p className="text-xs text-muted-foreground">{email.length > 0 ? email : '—'}</p>
      <span className="mt-1 text-[11px] font-semibold uppercase tracking-wider text-accent-blue">
        {user?.role_code ?? '—'}
      </span>
    </div>
  );
}

export interface ProfileMenuPanelProps {
  user: AuthUser | null;
  onSelectPassword: () => void;
  onSelectLogout: () => void;
}

/** Panel menu (presentasional). */
export function ProfileMenuPanel({ user, onSelectPassword, onSelectLogout }: ProfileMenuPanelProps) {
  return (
    <div
      role="menu"
      data-profile-menu="true"
      className="absolute right-0 z-30 mt-2 w-64 rounded-card border border-border/80 bg-popover p-2 shadow-pill"
    >
      <div className="px-2 py-1.5">
        <ProfileSummary user={user} />
      </div>

      <hr className="my-1 border-border/60" />

      <button role="menuitem" type="button" onClick={onSelectPassword} className={MENU_ITEM}>
        <KeyRound className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
        Ganti Password
      </button>
      <button
        role="menuitem"
        type="button"
        onClick={onSelectLogout}
        className={cn(MENU_ITEM, 'text-accent-coral')}
      >
        <LogOut className="h-4 w-4 shrink-0 text-accent-coral" aria-hidden="true" />
        Logout
      </button>
    </div>
  );
}

export interface ChangePasswordFieldsProps {
  oldPassword: string;
  newPassword: string;
  confirmPassword: string;
  error: string | null;
  info: string | null;
  disabled: boolean;
  onOldPasswordChange: (value: string) => void;
  onNewPasswordChange: (value: string) => void;
  onConfirmPasswordChange: (value: string) => void;
}

/** Isi modal ganti password (presentasional). */
export function ChangePasswordFields(props: ChangePasswordFieldsProps) {
  return (
    <div data-change-password="true" className="flex flex-col gap-3">
      <Input
        label="Password lama"
        name="old_password"
        type="password"
        autoComplete="current-password"
        value={props.oldPassword}
        disabled={props.disabled}
        onChange={(event) => props.onOldPasswordChange(event.target.value)}
      />
      <Input
        label="Password baru"
        name="new_password"
        type="password"
        autoComplete="new-password"
        value={props.newPassword}
        disabled={props.disabled}
        onChange={(event) => props.onNewPasswordChange(event.target.value)}
      />
      <Input
        label="Konfirmasi password baru"
        name="confirm_password"
        type="password"
        autoComplete="new-password"
        value={props.confirmPassword}
        disabled={props.disabled}
        onChange={(event) => props.onConfirmPasswordChange(event.target.value)}
      />

      {props.error !== null ? (
        <p role="alert" className="text-xs text-accent-coral">
          {props.error}
        </p>
      ) : null}
      {props.info !== null ? (
        <p role="status" className="text-xs text-accent-blue">
          {props.info}
        </p>
      ) : null}
    </div>
  );
}

interface ProfileMenuProps {
  /** Label role UI (TopBar yang menghitung, mis. dari `ROLE_LABELS[useRole()]`). */
  roleLabel: string;
}

/** Pill user + menu akun (Ganti Password / Logout). Butuh `<AuthProvider>` di atasnya. */
export function ProfileMenu({ roleLabel }: ProfileMenuProps) {
  const { user, logout, changePassword } = useAuth();
  const navigate = useNavigate();
  const containerRef = useRef<HTMLDivElement | null>(null);

  const [open, setOpen] = useState(false);
  const [passwordOpen, setPasswordOpen] = useState(false);
  const [oldPassword, setOldPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Tutup menu saat Escape / klik di luar (menu adalah popover, bukan dialog).
  useEffect(() => {
    if (!open) return;

    function handlePointer(event: MouseEvent): void {
      const target = event.target as Node | null;
      if (containerRef.current !== null && target !== null && !containerRef.current.contains(target)) {
        setOpen(false);
      }
    }

    function handleKey(event: KeyboardEvent): void {
      if (event.key === 'Escape') setOpen(false);
    }

    document.addEventListener('mousedown', handlePointer);
    document.addEventListener('keydown', handleKey);

    return () => {
      document.removeEventListener('mousedown', handlePointer);
      document.removeEventListener('keydown', handleKey);
    };
  }, [open]);

  const initials = initialsOf(user);

  function closePasswordModal(): void {
    setPasswordOpen(false);
    setOldPassword('');
    setNewPassword('');
    setConfirmPassword('');
    setError(null);
    setInfo(null);
  }

  async function submitPassword(): Promise<void> {
    if (busy) return;

    const invalid = passwordChangeError({ oldPassword, newPassword, confirmPassword });
    if (invalid !== null) {
      setError(invalid);
      setInfo(null);
      return;
    }

    setBusy(true);
    setError(null);
    setInfo(null);

    try {
      await changePassword(oldPassword, newPassword);
      setInfo(LOGIN_MESSAGES.passwordChanged);
      setOldPassword('');
      setNewPassword('');
      setConfirmPassword('');
    } catch (caught) {
      setError(errorMessageOf(caught));
    } finally {
      setBusy(false);
    }
  }

  async function handleLogout(): Promise<void> {
    setOpen(false);
    await logout(); // best-effort: state lokal dibersihkan walau request gagal
    navigate(LOGIN_PATH, { replace: true });
  }

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="Menu akun"
        data-profile-trigger="true"
        onClick={() => setOpen((current) => !current)}
        className={cn(
          PILL,
          'gap-2 border border-border/80 bg-card py-1 pr-2 pl-3 text-foreground hover:bg-muted',
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2',
        )}
      >
        <span className="hidden text-right sm:block">
          <span className="block text-xs font-semibold text-foreground">{displayNameOf(user)}</span>
          <span className="block text-[11px] font-medium text-muted-foreground">{roleLabel}</span>
        </span>
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-pill bg-primary text-[11px] font-semibold text-primary-foreground">
          {initials.length > 0 ? (
            initials
          ) : (
            <UserRound className="h-4 w-4" aria-hidden="true" />
          )}
        </span>
        <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
      </button>

      {open ? (
        <ProfileMenuPanel
          user={user}
          onSelectPassword={() => {
            setOpen(false);
            setPasswordOpen(true);
          }}
          onSelectLogout={() => {
            void handleLogout();
          }}
        />
      ) : null}

      <Modal
        open={passwordOpen}
        onOpenChange={(next) => {
          if (next) setPasswordOpen(true);
          else closePasswordModal();
        }}
        title="Ganti Password"
        description="Masukkan password lama, lalu password baru (minimal 8 karakter)."
        footer={
          <>
            <Button variant="secondary" onClick={closePasswordModal}>
              Batal
            </Button>
            <Button
              icon={KeyRound}
              loading={busy}
              onClick={() => {
                void submitPassword();
              }}
            >
              Simpan
            </Button>
          </>
        }
      >
        <ChangePasswordFields
          oldPassword={oldPassword}
          newPassword={newPassword}
          confirmPassword={confirmPassword}
          error={error}
          info={info}
          disabled={busy}
          onOldPasswordChange={setOldPassword}
          onNewPasswordChange={setNewPassword}
          onConfirmPasswordChange={setConfirmPassword}
        />
      </Modal>
    </div>
  );
}

