import { useState } from 'react';
import { Navigate, useLocation, useNavigate } from 'react-router-dom';
import { AlertCircle, Delete, Eraser, Factory, LogIn, Tablet } from 'lucide-react';
import { loadClientConfig } from '@/app/config';
import { Button } from '@/components/atoms/Button';
import { Checkbox } from '@/components/atoms/Checkbox';
import { Input } from '@/components/atoms/Input';
import { Tabs } from '@/components/atoms/Tabs';
import { useAuth } from '@/hooks/auth-context';
import { useDeviceMode } from '@/hooks/useDeviceMode';
import { cn } from '@/lib/cn';
import { deviceInfoText, isSwitchIntent } from '@/lib/device-mode';
import {
  applyOperatorKey,
  DEFAULT_LOGIN_TAB,
  errorMessageOf,
  isOperatorCodeComplete,
  LOGIN_MESSAGES,
  LOGIN_PATH,
  LOGIN_TABS,
  NUMPAD_KEYS,
  NUMPAD_LABELS,
  operatorCodeSlots,
  persistRememberedUsername,
  postLoginPath,
  readRedirectTarget,
  readRememberedUsername,
  type LoginTab,
} from '@/lib/login-form';
import { CARD, PILL } from '@/lib/tokens';

/**
 * LoginPage.tsx — halaman login MES (F6.2), DI LUAR App Shell (full-screen card).
 *
 * Dua tab (kontrak brief):
 *  1. **Admin/Supervisor** → username + password + "Ingat saya" (E1 `POST /auth/login/`);
 *  2. **Operator** → numpad besar 4 digit (E2 `POST /auth/login-operator/`, sesi 8 jam).
 *
 * Catatan "Ingat saya": backend F6.1 **tidak punya** opsi remember-me (umur sesi ditentukan
 * server), jadi centang ini dipakai untuk mengingat **username** di perangkat ini
 * (`persistRememberedUsername`) — bukan janji "sesi tak pernah habis".
 *
 * Redirect setelah sukses: `?redirect=` (kalau sah) atau `/dashboard`.
 *
 * Struktur: `LoginPage` (state + `useAuth`) merender `LoginCard` presentasional supaya
 * perilakunya bisa diuji tanpa DOM (`tests/unit/pages/login-page.test.ts`).
 */

const NUMPAD_ICONS: Record<string, typeof Delete> = {
  backspace: Delete,
  clear: Eraser,
};

/** Header kartu: ikon + nama client (dari `VITE_CLIENT_NAME`, fallback "MES Client"). */
export function LoginBrand() {
  return (
    <div className="flex flex-col items-center gap-2">
      <span className="flex h-12 w-12 items-center justify-center rounded-pill bg-primary text-primary-foreground shadow-pill">
        <Factory className="h-6 w-6" aria-hidden="true" />
      </span>
      <p className="text-lg font-bold tracking-tight text-foreground">
        {loadClientConfig().name}
      </p>
      <p className="text-xs font-medium text-muted-foreground">
        Manufacturing Execution System
      </p>
    </div>
  );
}

/** Banner error (`role="alert"` supaya dibacakan screen reader). */
export function LoginError({ message }: { message: string | null }) {
  if (message === null) return null;

  return (
    <p
      role="alert"
      data-login-error="true"
      className="flex items-start gap-2 rounded-lg border border-accent-coral/40 bg-accent-coral/10 px-3 py-2 text-sm text-accent-coral"
    >
      <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
      <span>{message}</span>
    </p>
  );
}

export interface AdminLoginFormProps {
  username: string;
  password: string;
  remember: boolean;
  busy: boolean;
  onUsernameChange: (value: string) => void;
  onPasswordChange: (value: string) => void;
  onRememberChange: (value: boolean) => void;
  onSubmit: () => void;
}

/** Form tab admin/supervisor (username + password + ingat saya). */
export function AdminLoginForm({
  username,
  password,
  remember,
  busy,
  onUsernameChange,
  onPasswordChange,
  onRememberChange,
  onSubmit,
}: AdminLoginFormProps) {
  return (
    <form
      data-login-form="admin"
      className="flex flex-col gap-3"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
    >
      <Input
        label="Username"
        name="username"
        autoComplete="username"
        value={username}
        onChange={(event) => onUsernameChange(event.target.value)}
      />
      <Input
        label="Password"
        name="password"
        type="password"
        autoComplete="current-password"
        value={password}
        onChange={(event) => onPasswordChange(event.target.value)}
      />
      <Checkbox
        label="Ingat saya"
        checked={remember}
        onCheckedChange={onRememberChange}
      />
      <Button type="submit" size="lg" icon={LogIn} loading={busy} className="mt-1 w-full">
        Login
      </Button>
    </form>
  );
}

export interface OperatorNumpadProps {
  code: string;
  busy: boolean;
  onKey: (key: string) => void;
  onSubmit: () => void;
}

/** Tab operator: display 4 slot + numpad besar (digit 0-9, bersihkan, hapus). */
export function OperatorNumpad({ code, busy, onKey, onSubmit }: OperatorNumpadProps) {
  const complete = isOperatorCodeComplete(code);

  return (
    <div data-login-form="operator" className="flex flex-col gap-4">
      <div className="flex items-center justify-center gap-2" aria-label="Kode operator">
        {operatorCodeSlots(code).map((digit, index) => (
          <span
            key={index}
            data-code-slot={digit === '' ? 'empty' : 'filled'}
            className={cn(
              'flex h-12 w-10 items-center justify-center rounded-lg border text-xl font-bold tabular-nums',
              digit === ''
                ? 'border-border/80 bg-card text-muted-foreground'
                : 'border-primary bg-primary/10 text-foreground',
            )}
          >
            {digit === '' ? '·' : digit}
          </span>
        ))}
      </div>

      <div className="grid grid-cols-3 gap-2">
        {NUMPAD_KEYS.map((key) => {
          const label = NUMPAD_LABELS[key] ?? key;
          const Icon = NUMPAD_ICONS[key];

          return (
            <button
              key={key}
              type="button"
              onClick={() => onKey(key)}
              aria-label={label}
              className={cn(
                PILL,
                'h-14 w-full gap-2 border border-border/80 bg-card text-lg font-semibold text-foreground hover:bg-muted',
                'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2',
              )}
            >
              {Icon !== undefined ? (
                <Icon className="h-5 w-5" aria-hidden="true" />
              ) : (
                <span aria-hidden="true">{key}</span>
              )}
            </button>
          );
        })}
      </div>

      <Button
        type="button"
        size="lg"
        icon={LogIn}
        loading={busy}
        disabled={!complete}
        onClick={onSubmit}
        className="w-full"
      >
        Login
      </Button>
    </div>
  );
}

export interface LoginCardProps {
  tab: LoginTab;
  onTabChange: (tab: LoginTab) => void;
  username: string;
  password: string;
  remember: boolean;
  code: string;
  busy: boolean;
  error: string | null;
  /**
   * F6.4 — info perangkat ter-bind (`null` = tidak ditampilkan). Diisi halaman hanya saat
   * cookie device dikenali backend, supaya operator tahu kenapa login tidak diperlukan.
   */
  deviceInfo?: string | null;
  onUsernameChange: (value: string) => void;
  onPasswordChange: (value: string) => void;
  onRememberChange: (value: boolean) => void;
  onCodeKey: (key: string) => void;
  onSubmitAdmin: () => void;
  onSubmitOperator: () => void;
}

/** Kartu login presentasional (logo + tab switcher + form aktif + info bawah). */
export function LoginCard(props: LoginCardProps) {
  return (
    <main
      data-login-page="true"
      className="flex min-h-screen items-center justify-center p-4"
    >
      <section className={cn(CARD, 'w-full max-w-sm')}>
        <LoginBrand />

        <Tabs
          className="mt-5"
          tabs={LOGIN_TABS.map((item) => ({ id: item.id, label: item.label }))}
          active={props.tab}
          onChange={(id) => props.onTabChange(id === 'operator' ? 'operator' : 'admin')}
        />

        <div className="mt-4 flex flex-col gap-3">
          {props.deviceInfo === null || props.deviceInfo === undefined ? null : (
            <div
              data-login-device-info="true"
              className="flex flex-col gap-1 rounded-lg border border-accent-blue/40 bg-accent-blue/10 px-3 py-2 text-xs text-accent-blue"
            >
              <span className="flex items-start gap-2">
                <Tablet className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
                <span>{props.deviceInfo}</span>
              </span>
              {/* Tautan `?switch=1` = cara masuk ke form login walau device ter-bind
                  (mis. supervisor mau login pakai akun sendiri di kios yang sama). */}
              <a
                href={`${LOGIN_PATH}?switch=1`}
                className="pl-6 font-semibold underline underline-offset-2"
              >
                Login sebagai user lain
              </a>
            </div>
          )}

          <LoginError message={props.error} />

          {props.tab === 'admin' ? (
            <AdminLoginForm
              username={props.username}
              password={props.password}
              remember={props.remember}
              busy={props.busy}
              onUsernameChange={props.onUsernameChange}
              onPasswordChange={props.onPasswordChange}
              onRememberChange={props.onRememberChange}
              onSubmit={props.onSubmitAdmin}
            />
          ) : (
            <OperatorNumpad
              code={props.code}
              busy={props.busy}
              onKey={props.onCodeKey}
              onSubmit={props.onSubmitOperator}
            />
          )}
        </div>

        <p className="mt-5 text-center text-[11px] text-muted-foreground">
          {LOGIN_MESSAGES.contactAdmin}
        </p>
      </section>
    </main>
  );
}

/**
 * Halaman login: state form + pemanggilan `useAuth()`.
 *
 * Redirect (FIX ROUTE): HANYA user yang sudah login (mis. user membuka `/login` langsung
 * atau kios dengan cookie device ber-user yang dibaca backend sebagai sesi). Cookie device
 * ter-bind TANPA sesi tidak lagi melewati form login — sebab binding tanpa user tetap
 * anonim di backend (semua API 401/403). `?switch=1` menahan redirect supaya user bisa
 * login dengan akun lain di perangkat yang sama; setelah submit sukses hal yang sama
 * dilakukan lewat `navigate()`.
 */
export function LoginPage() {
  const { user, login, loginOperator } = useAuth();
  const device = useDeviceMode();
  const navigate = useNavigate();
  const location = useLocation();

  const [tab, setTab] = useState<LoginTab>(DEFAULT_LOGIN_TAB);
  const [username, setUsername] = useState(() => readRememberedUsername());
  const [password, setPassword] = useState('');
  const [remember, setRemember] = useState(() => readRememberedUsername().length > 0);
  const [code, setCode] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const redirect = readRedirectTarget(location.search);
  const target = postLoginPath(redirect);

  // FIX ROUTE — perangkat ter-bind TIDAK lagi melewati login (dulu `device.bound`).
  // Bukti boleh-masuk hanya sesi: binding device tanpa user tetap ANONIM di backend
  // (semua API 401/403 → halaman kosong), sedangkan kios ber-user sudah masuk lewat
  // `user !== null` karena cookie-nya sendiri yang mengisi sesi.
  // `?switch=1` (tautan "Login sebagai user lain") menahan redirect ini.
  if (user !== null && !isSwitchIntent(location.search)) return <Navigate to={target} replace />;

  async function submitAdmin(): Promise<void> {
    if (busy) return;

    if (username.trim().length === 0 || password.length === 0) {
      setError(LOGIN_MESSAGES.missingCredentials);
      return;
    }

    setBusy(true);
    setError(null);

    try {
      await login(username, password);
      persistRememberedUsername(username, remember);
      navigate(target, { replace: true });
    } catch (caught) {
      setError(errorMessageOf(caught));
    } finally {
      setBusy(false);
    }
  }

  async function submitOperator(): Promise<void> {
    if (busy) return;

    if (!isOperatorCodeComplete(code)) {
      setError(LOGIN_MESSAGES.incompleteCode);
      return;
    }

    setBusy(true);
    setError(null);

    try {
      await loginOperator(code);
      navigate(target, { replace: true });
    } catch (caught) {
      setError(errorMessageOf(caught));
      // Kode salah → kosongkan supaya operator bisa langsung mengetik ulang.
      setCode('');
    } finally {
      setBusy(false);
    }
  }

  return (
    <LoginCard
      tab={tab}
      onTabChange={(next) => {
        setTab(next);
        setError(null);
      }}
      username={username}
      password={password}
      remember={remember}
      code={code}
      busy={busy}
      error={error}
      deviceInfo={device.bound ? deviceInfoText(device.profile, device.wcCode) : null}
      onUsernameChange={setUsername}
      onPasswordChange={setPassword}
      onRememberChange={setRemember}
      onCodeKey={(key) => setCode((current) => applyOperatorKey(current, key))}
      onSubmitAdmin={() => {
        void submitAdmin();
      }}
      onSubmitOperator={() => {
        void submitOperator();
      }}
    />
  );
}


