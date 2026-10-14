import type { CSSProperties, ReactNode } from 'react';
import type { ModeOption, UiMode } from '@/app/useMode';

/**
 * LayoutShell.tsx — kerangka BERSAMA 3 mode UX (§3 blueprint).
 *
 * Yang berbeda antar mode hanya: `mode` (atribut + label), `density` (jarak & lebar), dan
 * slot tambahan (`dock`). Logika aplikasi TIDAK diduplikasi di layout — layout hanya shell.
 * Tanpa hook → bisa dipanggil langsung di test (pohon element, tanpa DOM).
 */

export type LayoutDensity = 'compact' | 'touch' | 'fullscreen';

export interface LayoutProps {
  children: ReactNode;
  clientName?: string;
  logo?: string;
  /** Daftar mode yang bisa dipilih (dari `useMode()`), tombol navigasi. */
  modes?: ModeOption[];
  onSelectMode?: (mode: UiMode) => void;
  className?: string;
}

export interface LayoutShellProps extends LayoutProps {
  mode: UiMode;
  density: LayoutDensity;
  /** Slot bawah (mis. status koneksi di mode operator). */
  dock?: ReactNode;
}

const ROOT_STYLE: CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  minHeight: '100vh',
};

const HEADER_STYLE: CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: '0.75rem',
  flexWrap: 'wrap',
  padding: '0.625rem 1rem',
  borderBottom: '1px solid var(--color-border, currentColor)',
  backdropFilter: 'blur(8px)',
};

const TITLE_STYLE: CSSProperties = {
  fontSize: '0.875rem',
  fontWeight: 700,
  marginRight: 'auto',
};

const LOGO_STYLE: CSSProperties = {
  height: '1.5rem',
  width: 'auto',
};

const SWITCH_STYLE: CSSProperties = {
  display: 'flex',
  gap: '0.25rem',
};

const PILL_BASE_STYLE: CSSProperties = {
  padding: '0.25rem 0.625rem',
  borderRadius: '9999px',
  fontSize: '0.6875rem',
  fontWeight: 600,
  cursor: 'pointer',
  border: '1px solid var(--color-border, currentColor)',
};

const PILL_ACTIVE_STYLE: CSSProperties = {
  ...PILL_BASE_STYLE,
  background: 'var(--color-primary, transparent)',
  color: 'var(--color-primary-foreground, inherit)',
};

const PILL_IDLE_STYLE: CSSProperties = {
  ...PILL_BASE_STYLE,
  background: 'var(--color-card, transparent)',
  color: 'var(--color-muted-foreground, inherit)',
};

const DOCK_STYLE: CSSProperties = {
  marginTop: 'auto',
  display: 'flex',
  gap: '0.75rem',
  alignItems: 'center',
  padding: '0.75rem 1rem',
  borderTop: '1px solid var(--color-border, currentColor)',
};

function mainStyle(density: LayoutDensity): CSSProperties {
  if (density === 'touch') {
    return {
      display: 'flex',
      flexDirection: 'column',
      gap: '1rem',
      padding: '0.75rem',
      flex: '1 1 auto',
    };
  }

  if (density === 'fullscreen') {
    return {
      display: 'flex',
      flexDirection: 'column',
      gap: '0.5rem',
      padding: '0.5rem',
      flex: '1 1 auto',
    };
  }

  return {
    display: 'grid',
    gap: '1rem',
    padding: '1rem',
    width: '100%',
    maxWidth: '72rem',
    margin: '0 auto',
    flex: '1 1 auto',
  };
}

export function LayoutShell(props: LayoutShellProps): ReactNode {
  const { mode, density, clientName, logo, modes, onSelectMode, dock, className } = props;

  return (
    <div
      data-mode={mode}
      data-density={density}
      data-layout-shell="true"
      style={ROOT_STYLE}
      className={className}
    >
      <header data-layout-header={mode} style={HEADER_STYLE}>
        {logo === undefined || logo.length === 0 ? null : (
          <img data-layout-logo="true" src={logo} alt="" style={LOGO_STYLE} />
        )}

        <strong data-layout-title="true" style={TITLE_STYLE}>
          {clientName ?? ''}
        </strong>

        <nav data-layout-mode-switch="true" aria-label="Mode tampilan" style={SWITCH_STYLE}>
          {(modes ?? []).map((option) => (
            // key = id mode (stabil), bukan index
            <button
              key={option.id}
              type="button"
              data-mode-option={option.id}
              data-mode-active={option.id === mode ? 'true' : 'false'}
              onClick={() => onSelectMode?.(option.id)}
              style={option.id === mode ? PILL_ACTIVE_STYLE : PILL_IDLE_STYLE}
            >
              {option.label}
            </button>
          ))}
        </nav>
      </header>

      <main data-layout-main={mode} style={mainStyle(density)}>
        {props.children}
      </main>

      {dock === undefined ? null : (
        <footer data-layout-dock="true" style={DOCK_STYLE}>
          {dock}
        </footer>
      )}
    </div>
  );
}
