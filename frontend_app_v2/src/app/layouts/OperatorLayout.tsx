import type { ReactNode } from 'react';
import { LayoutShell, type LayoutProps } from './LayoutShell';

/**
 * OperatorLayout — mode shopfloor (HP/Kiosk/Scanner): tombol besar (target sentuh ≥56px),
 * zero text input, offline-first. Wrapper tipis + slot `dock` untuk status di bawah.
 */

/** Target sentuh minimum (h-14 = 56px, §12.2). */
export const OPERATOR_TOUCH_TARGET_PX = 56;

export interface OperatorLayoutProps extends LayoutProps {
  dock?: ReactNode;
}

const TOUCH_STYLE = {
  display: 'flex',
  flexDirection: 'column',
  gap: '1rem',
  minHeight: `${OPERATOR_TOUCH_TARGET_PX * 4}px`,
} as const;

export function OperatorLayout(props: OperatorLayoutProps): ReactNode {
  const { dock, ...layoutProps } = props;

  return (
    <LayoutShell mode="operator" density="touch" dock={dock} {...layoutProps}>
      <div
        data-layout-touch="true"
        data-touch-target={OPERATOR_TOUCH_TARGET_PX}
        style={TOUCH_STYLE}
      >
        {props.children}
      </div>
    </LayoutShell>
  );
}
