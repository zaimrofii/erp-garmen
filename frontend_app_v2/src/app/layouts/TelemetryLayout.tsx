import type { ReactNode } from 'react';
import { LayoutShell, type LayoutProps } from './LayoutShell';

/**
 * TelemetryLayout — mode layar besar (fullscreen, tanpa chrome tebal).
 * Wrapper tipis: konten telemetry mengisi seluruh area.
 */

const FULLSCREEN_STYLE = {
  display: 'flex',
  flexDirection: 'column',
  gap: '0.5rem',
  flex: '1 1 auto',
  minHeight: '60vh',
} as const;

export function TelemetryLayout(props: LayoutProps): ReactNode {
  return (
    <LayoutShell mode="telemetry" density="fullscreen" {...props}>
      <div data-layout-fullscreen="true" style={FULLSCREEN_STYLE}>
        {props.children}
      </div>
    </LayoutShell>
  );
}
