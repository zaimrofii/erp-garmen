import type { ReactNode } from 'react';
import { LayoutShell, type LayoutProps } from './LayoutShell';

/**
 * ManagementLayout — mode desktop (glass-card, densitas tinggi, fokus meja kerja).
 * Wrapper tipis: yang berbeda hanya `mode`, `density`, dan grid-nya.
 */

export const MANAGEMENT_GRID_COLUMNS = 2;

const GRID_STYLE = {
  display: 'grid',
  gridTemplateColumns: `repeat(auto-fit, minmax(${MANAGEMENT_GRID_COLUMNS * 8}rem, 1fr))`,
  gap: '1rem',
  alignItems: 'start',
} as const;

export function ManagementLayout(props: LayoutProps): ReactNode {
  return (
    <LayoutShell mode="management" density="compact" {...props}>
      <div data-layout-grid="dense" style={GRID_STYLE}>
        {props.children}
      </div>
    </LayoutShell>
  );
}
