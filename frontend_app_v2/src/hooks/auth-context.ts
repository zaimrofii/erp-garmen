import { createContext, useContext } from 'react';
import type { AuthUser } from '@/api/auth';

/**
 * auth-context.ts — konteks auth + hook `useAuth` (F6.2).
 *
 * Dipisah dari `useAuth.tsx` (yang hanya mengekspor komponen `AuthProvider`) karena aturan
 * lint `react(only-export-components)`: satu file campur komponen + non-komponen mematikan
 * Fast Refresh. Pola yang sama dipakai runtime global: `app/AppRuntimeProvider.tsx`
 * (komponen) + `app/app-runtime.ts` (hook/konstanta).
 */

export interface AuthContextValue {
  /** User aktif (null = belum login). */
  user: AuthUser | null;
  /** true selama probe sesi pertama berjalan (AuthGuard menampilkan spinner). */
  loading: boolean;
  login: (username: string, password: string) => Promise<AuthUser>;
  loginOperator: (operatorCode: string) => Promise<AuthUser>;
  logout: () => Promise<void>;
  refresh: () => Promise<AuthUser | null>;
  changePassword: (oldPassword: string, newPassword: string) => Promise<void>;
}

export const AuthContext = createContext<AuthContextValue | null>(null);

/** Hook auth — WAJIB dipakai di dalam `<AuthProvider>` (kalau tidak → error jelas). */
export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);

  if (context === null) {
    throw new Error('useAuth() dipakai di luar <AuthProvider> (F6.2).');
  }

  return context;
}
