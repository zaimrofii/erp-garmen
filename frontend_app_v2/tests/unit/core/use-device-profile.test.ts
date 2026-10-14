import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  DEVICE_PROFILES,
  DEVICE_PROFILE_REFRESH_EVENT,
  FALLBACK_DEVICE_PROFILE,
  deviceProfileRefresh,
  isDeviceHintMismatch,
  normalizeDeviceProfile,
  resolveLocalProfile,
} from '@/core/useDeviceProfile';

/** F7 — resolver 5-level (sudah ada sejak Fase 14) + seam refresh baru. */

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('F7 — DEVICE_PROFILES (kontrak §2.2)', () => {
  it('4 kode sah, nilai lain ditolak', () => {
    expect([...DEVICE_PROFILES]).toEqual(['OPERATOR_HP', 'KIOSK_TABLET', 'SCANNER_USB', 'DESKTOP']);
    expect(normalizeDeviceProfile(' scanner_usb ')).toBe('SCANNER_USB');
    expect(normalizeDeviceProfile('KIOS')).toBeNull();
    expect(normalizeDeviceProfile(null)).toBeNull();
  });
});

describe('F7 — resolveLocalProfile (level 1/3/4/5)', () => {
  it('level 1 URL override menang atas preferensi & hint', () => {
    const resolved = resolveLocalProfile({
      urlOverride: 'DESKTOP',
      userPreference: 'OPERATOR_HP',
      metadataDeviceHint: 'KIOSK_TABLET',
    });

    expect(resolved.profile).toBe('DESKTOP');
    expect(resolved.source).toEqual({ level: 1, confidence: 'high', reason: 'url_override' });
  });

  it('level 3 preferensi user mengalahkan hint', () => {
    const resolved = resolveLocalProfile({ userPreference: 'SCANNER_USB', metadataDeviceHint: 'DESKTOP' });

    expect(resolved.profile).toBe('SCANNER_USB');
    expect(resolved.source.reason).toBe('user_preference');
    expect(resolved.source.level).toBe(3);
  });

  it('level 4 device_hint backend', () => {
    const resolved = resolveLocalProfile({ metadataDeviceHint: 'KIOSK_TABLET' });

    expect(resolved.profile).toBe('KIOSK_TABLET');
    expect(resolved.source).toEqual({ level: 4, confidence: 'medium', reason: 'backend_hint' });
  });

  it('level 5 fallback OPERATOR_HP', () => {
    const resolved = resolveLocalProfile({});

    expect(resolved.profile).toBe(FALLBACK_DEVICE_PROFILE);
    expect(resolved.source).toEqual({ level: 5, confidence: 'low', reason: 'fallback' });
  });

  it('hint beda dari profile final → mismatch (bukan error)', () => {
    expect(isDeviceHintMismatch('OPERATOR_HP', 'KIOSK_TABLET')).toBe(true);
    expect(isDeviceHintMismatch('OPERATOR_HP', 'OPERATOR_HP')).toBe(false);
    expect(isDeviceHintMismatch('OPERATOR_HP', 'tidak-dikenal')).toBe(false);
  });
});

describe('F7/7.4 — sean refresh global', () => {
  it('tanpa DOM (SSR/test) → no-op, tidak throw', () => {
    expect(() => deviceProfileRefresh()).not.toThrow();
  });

  it('dengan window → dispatch CustomEvent bernama DEVICE_PROFILE_REFRESH_EVENT', () => {
    class FakeCustomEvent {
      constructor(public type: string) {}
    }

    const dispatchEvent = vi.fn();
    vi.stubGlobal('CustomEvent', FakeCustomEvent);
    vi.stubGlobal('dispatchEvent', dispatchEvent);

    deviceProfileRefresh();

    expect(dispatchEvent).toHaveBeenCalledTimes(1);

    const event = dispatchEvent.mock.calls[0]?.[0] as FakeCustomEvent;

    expect(event).toBeInstanceOf(FakeCustomEvent);
    expect(event.type).toBe(DEVICE_PROFILE_REFRESH_EVENT);
  });

  it('listener global menerima event (kontrak seam)', () => {
    const received: string[] = [];
    const listener = (event: Event): void => {
      received.push(event.type);
    };

    globalThis.addEventListener(DEVICE_PROFILE_REFRESH_EVENT, listener);

    try {
      deviceProfileRefresh();
    } finally {
      globalThis.removeEventListener(DEVICE_PROFILE_REFRESH_EVENT, listener);
    }

    expect(received).toEqual([DEVICE_PROFILE_REFRESH_EVENT]);
  });
});
