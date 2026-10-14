import { Moon, Smartphone, Sun, WifiOff } from 'lucide-react';
import { AppMenuBar } from '@/components/organisms/AppMenuBar';
import { ProfileMenu } from '@/components/molecules/ProfileMenu';
import { useOffline } from '@/app/app-runtime';
import type { NavApp } from '@/app/nav-config';
import { ROLE_LABELS, useRole } from '@/app/useRole';
import { useDeviceMode } from '@/hooks/useDeviceMode';
import { useThemeMode } from '@/hooks/use-theme-mode';
import { cn } from '@/lib/cn';
import { deviceBadgeLabel } from '@/lib/device-mode';
import { BADGE, PILL } from '@/lib/tokens';

/**
 * TopBar.tsx (layout) - bilah atas kontekstual per aplikasi.
 *
 * Basis desain = referensi `AppHeader` (mask-image fade, dark toggle pill, online badge,
 * user pill) + menu kontekstual per app.
 *
 * F5: baris menu kontekstual lama (`TopBarMenu`, tautan datar) DIGANTI `<AppMenuBar />`
 * (dropdown per app, Odoo-style) - signature komponen ini tidak berubah.
 *
 * F16 (fix): sumber menu diperbaiki. Dulu TopBar mengisi menu bar dengan **daftar APP**
 * (hasil penyaringan helper `menu-config` terhadap app yang boleh dilihat role), sehingga
 * TopBar menampilkan ULANG daftar app (duplikat `Sidebar`). Sekarang menu diambil dari
 * **`app.topbar`** = menu DALAM app yang sedang aktif (mis. Inventory →
 * Products/Operations/Reporting/Configuration); item tanpa `children` dirender LINK,
 * yang punya `children` dirender dropdown. `Sidebar` tetap satu-satunya daftar app.
 *
 * Catatan: badge Online/Offline membaca SATU queue aplikasi lewat `useOffline()`
 * (Fase 17) - offline menampilkan warna coral + jumlah aksi pending.
 *
 * F6.2: pill user dummy DIGANTI `<ProfileMenu />` — nama/email/inisial dari user nyata
 * (`useAuth()`), plus menu akun (Ganti Password / Logout). Label role tetap dari
 * `ROLE_LABELS[useRole()]` supaya konsisten dengan sidebar yang difilter per role.
 */

interface TopBarProps {
  app: NavApp | undefined;
  currentPath: string;
  onNavigate: (path: string) => void;
}

export function TopBar({ app, currentPath, onNavigate }: TopBarProps) {
  const { isDark, toggle } = useThemeMode();
  const role = useRole();
  const { isOnline, pendingCount } = useOffline();
  const device = useDeviceMode();

  // F16 — menu DALAM app aktif (bukan daftar app). App tanpa topbar (mis. Dashboard/AI
  // yang halamannya di `app.path` sendiri) → baris menu kosong, judul app tetap tampil.
  const items = app?.topbar ?? [];

  return (
    <header className="sticky top-0 z-20 flex flex-col gap-4 px-4 pt-4 pb-2 md:px-6 lg:flex-row lg:items-center lg:justify-between">
      {/*
        FIX (dropdown akun tidak muncul) - lapisan dekoratif TERPISAH untuk mask. Dulu mask
        ada di <header>: area mask default membatasi SEMUA isi yang dilukis turunannya ke
        kotak header, sehingga panel dropdown (posisi absolute, di luar kotak header) dan
        Modal ganti password (posisi fixed) ikut terpotong = tidak terlihat walau state-nya
        benar. Elemen di bawah tetap membawa efek kaca + mask yang sama supaya batas bawah
        header tetap lembut (yang memudar adalah latar buram, bukan overlay), dan <header>
        tidak lagi jadi acuan posisi bagi elemen fixed.
        NB: jangan menulis token seperti nama kelas Tailwind di komentar - pemindai
        Tailwind membaca berkas ini sebagai teks dan akan membuat rule baru.
      */}
      <div
        aria-hidden="true"
        data-topbar-fade="true"
        className="pointer-events-none absolute inset-0 backdrop-blur [mask-image:linear-gradient(to_bottom,black_70%,transparent_100%)]"
      />
      <div className="flex min-w-0 flex-col gap-2">
        <h1 className="text-2xl font-bold tracking-tight text-foreground">
          {app?.label ?? 'Dashboard'}
        </h1>

        <AppMenuBar items={items} currentPath={currentPath} onNavigate={onNavigate} />
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={toggle}
          aria-pressed={isDark}
          aria-label={isDark ? 'Aktifkan mode terang' : 'Aktifkan mode gelap'}
          className={cn(
            PILL,
            'gap-2 border border-border/80 bg-card px-3 py-2 text-foreground hover:bg-muted',
            'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2',
          )}
        >
          {isDark ? (
            <Sun className="h-4 w-4 shrink-0 text-accent-coral" aria-hidden="true" />
          ) : (
            <Moon className="h-4 w-4 shrink-0 text-accent-blue" aria-hidden="true" />
          )}
          <span className="text-sm font-medium">{isDark ? 'Terang' : 'Gelap'}</span>
        </button>

        <span
          className={cn(
            BADGE,
            isOnline
              ? 'bg-accent-blue/10 text-accent-blue'
              : 'bg-accent-coral/10 text-accent-coral',
          )}
        >
          {isOnline ? (
            <>
              <span className="h-1.5 w-1.5 rounded-pill bg-accent-blue" aria-hidden="true" />
              Online
            </>
          ) : (
            <>
              <WifiOff className="h-3 w-3" aria-hidden="true" />
              Offline {pendingCount}
            </>
          )}
        </span>

        {device.bound ? (
          /* F6.4 — mode device (kios/HP bersama): tampilkan badge perangkat, bukan menu akun. */
          <span
            data-device-badge="true"
            className={cn(BADGE, 'bg-accent-blue/10 text-accent-blue')}
          >
            <Smartphone className="h-3 w-3" aria-hidden="true" />
            {deviceBadgeLabel(device.profile, device.wcCode)}
          </span>
        ) : (
          <ProfileMenu roleLabel={ROLE_LABELS[role]} />
        )}
      </div>
    </header>
  );
}
