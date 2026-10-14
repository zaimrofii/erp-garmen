import type { CSSProperties, ReactNode } from 'react';
import type { OfflineAction } from '@/integrations/offline-queue';

/**
 * ConflictResolver.tsx — modal resolve konflik 409 dengan policy `manual` (§8.2, §5.2 backend-contract).
 *
 * Dipakai kalau `queue.flush()` melaporkan `conflicted` dengan `reason === 'conflict_manual'`.
 * **Tidak ada resolve otomatis** — operator yang memutuskan (3 opsi).
 *
 * Catatan kontrak: `OfflineAction` tidak punya field "state lokal" tersendiri, jadi state lokal
 * ditampilkan dari `expected_result.state` (state yang diharapkan saat aksi dibuat) bila ada.
 */

export type ConflictChoice = 'server_wins' | 'retry_force' | 'cancel';

export interface ConflictResolverCurrent {
  version: string;
  state: string;
  current_work_center?: string;
}

export interface ConflictResolverProps {
  open: boolean;
  action: OfflineAction;
  current: ConflictResolverCurrent;
  onResolve: (choice: ConflictChoice) => void;
  onClose: () => void;
}

const DIALOG_STYLE: CSSProperties = {
  position: 'fixed',
  inset: 'auto',
  margin: 'auto',
  minWidth: '20rem',
  maxWidth: '32rem',
  padding: '1rem',
  borderRadius: '0.75rem',
  border: '1px solid var(--color-border, currentColor)',
  background: 'var(--color-popover, var(--color-card, transparent))',
  color: 'var(--color-popover-foreground, inherit)',
  fontSize: '0.875rem',
};

const HEADER_STYLE: CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'space-between',
  gap: '1rem',
  marginBottom: '0.5rem',
  fontWeight: 600,
};

const CLOSE_STYLE: CSSProperties = {
  border: 'none',
  background: 'transparent',
  color: 'inherit',
  fontSize: '1rem',
  cursor: 'pointer',
  lineHeight: 1,
};

const CAPTION_STYLE: CSSProperties = {
  margin: '0 0 0.75rem',
  fontSize: '0.75rem',
  color: 'var(--color-muted-foreground)',
};

const GRID_STYLE: CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'auto 1fr',
  gap: '0.25rem 0.75rem',
  margin: '0 0 0.75rem',
};

const LABEL_STYLE: CSSProperties = {
  color: 'var(--color-muted-foreground)',
};

const VALUE_STYLE: CSSProperties = {
  fontWeight: 600,
  color: 'var(--color-foreground)',
};

const CHOICE_STYLE: CSSProperties = {
  padding: '0.5rem 0.875rem',
  borderRadius: '9999px',
  border: '1px solid var(--color-border, currentColor)',
  background: 'var(--color-primary, transparent)',
  color: 'var(--color-primary-foreground, inherit)',
  fontSize: '0.8125rem',
  fontWeight: 500,
  cursor: 'pointer',
  marginRight: '0.375rem',
};

const CANCEL_STYLE: CSSProperties = {
  ...CHOICE_STYLE,
  background: 'var(--color-card, transparent)',
  color: 'var(--color-foreground)',
};

export function ConflictResolver(props: ConflictResolverProps): ReactNode {
  // `open === false` → render null (tidak ada modal tersembunyi).
  if (!props.open) return null;

  const { action, current } = props;
  const localState = action.expected_result?.state ?? '—';

  return (
    <dialog open aria-modal="true" data-conflict-resolver="true" style={DIALOG_STYLE}>
      <div style={HEADER_STYLE}>
        <span>Konflik data (409)</span>
        <button
          type="button"
          data-conflict-close="true"
          aria-label="Tutup"
          onClick={props.onClose}
          style={CLOSE_STYLE}
        >
          ×
        </button>
      </div>

      <p style={CAPTION_STYLE}>
        Aksi <code>{action.path}</code> pada resource <code>{action.resource}</code> (#
        {action.resourceId}) ditolak karena versi datanya sudah berubah di server.
      </p>

      <dl style={GRID_STYLE}>
        <dt style={LABEL_STYLE}>Versi lokal</dt>
        <dd data-conflict-local-version="true" style={VALUE_STYLE}>
          {action.base_version}
        </dd>

        <dt style={LABEL_STYLE}>Versi server</dt>
        <dd data-conflict-server-version="true" style={VALUE_STYLE}>
          {current.version}
        </dd>

        <dt style={LABEL_STYLE}>State lokal</dt>
        <dd data-conflict-local-state="true" style={VALUE_STYLE}>
          {localState}
        </dd>

        <dt style={LABEL_STYLE}>State server</dt>
        <dd data-conflict-server-state="true" style={VALUE_STYLE}>
          {current.state}
        </dd>

        {current.current_work_center !== undefined ? (
          <>
            <dt style={LABEL_STYLE}>Work center</dt>
            <dd data-conflict-work-center="true" style={VALUE_STYLE}>
              {current.current_work_center}
            </dd>
          </>
        ) : null}
      </dl>

      <div>
        <button
          type="button"
          data-conflict-choice="server_wins"
          onClick={() => props.onResolve('server_wins')}
          style={CHOICE_STYLE}
        >
          Pakai Server
        </button>
        <button
          type="button"
          data-conflict-choice="retry_force"
          onClick={() => props.onResolve('retry_force')}
          style={CHOICE_STYLE}
        >
          Coba Paksa
        </button>
        <button
          type="button"
          data-conflict-choice="cancel"
          onClick={() => {
            props.onResolve('cancel');
            props.onClose();
          }}
          style={CANCEL_STYLE}
        >
          Batal
        </button>
      </div>
    </dialog>
  );
}
