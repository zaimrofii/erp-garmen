/**
 * feedback.ts - feedback audio + haptic + flash (Visual Design System v1.0 bagian 2.7).
 *
 * Aturan UX: setiap aksi (MULAI / SELESAI / SCRAP) WAJIB memberi feedback visual
 * + suara/haptic. Modul ini murni "keluaran perangkat" - tidak menyimpan state React:
 *
 *  - `playBeep`   -> Web Audio API (dibuat malas, SSR-safe, tidak pernah throw);
 *  - `haptic`     -> `navigator.vibrate` (diam di desktop);
 *  - `flashSuccess` / `flashError` -> helper imperatif overlay;
 *  - `flashOverlayClass` -> kelas overlay untuk komponen (`AnimatePresence` di Fase 15+).
 *
 * Warna overlay memakai token OKLCH `--color-accent-blue` / `--color-accent-coral`.
 */

export type BeepKind = 'success' | 'error' | 'warning';

export interface BeepPreset {
  /** Frekuensi dalam Hz. */
  freq: number;
  /** Durasi dalam milidetik. */
  duration: number;
  type: OscillatorType;
}

/** Scan/aksi sukses -> beep pitch tinggi; gagal -> low-pitch panjang; peringatan -> segitiga. */
export const BEEP: Record<BeepKind, BeepPreset> = {
  success: { freq: 1200, duration: 80, type: 'sine' },
  error: { freq: 320, duration: 200, type: 'square' },
  warning: { freq: 800, duration: 150, type: 'triangle' },
};

/** Context Web Audio singleton - dibuat malas supaya tidak melanggar kebijakan autoplay browser. */
let audioContext: AudioContext | null = null;

function ensureAudioContext(): AudioContext | null {
  if (typeof window === 'undefined') return null;
  if (typeof window.AudioContext === 'undefined') return null;

  if (audioContext === null) {
    try {
      audioContext = new window.AudioContext();
    } catch {
      return null;
    }
  }

  if (audioContext.state === 'suspended') {
    void audioContext.resume();
  }

  return audioContext;
}

/** Bunyikan beep sesuai jenis feedback. Diam (tanpa throw) kalau Web Audio tidak tersedia. */
export function playBeep(kind: BeepKind): void {
  const context = ensureAudioContext();
  if (context === null) return;

  const preset = BEEP[kind];
  const now = context.currentTime;
  const durationSec = preset.duration / 1000;

  const oscillator = context.createOscillator();
  const gain = context.createGain();

  oscillator.type = preset.type;
  oscillator.frequency.setValueAtTime(preset.freq, now);

  // Hindari gain 0 (exponentialRamp tidak boleh mulai dari 0).
  gain.gain.setValueAtTime(0.0001, now);
  gain.gain.exponentialRampToValueAtTime(0.2, now + 0.01);
  gain.gain.exponentialRampToValueAtTime(0.0001, now + durationSec);

  oscillator.connect(gain);
  gain.connect(context.destination);

  oscillator.start(now);
  oscillator.stop(now + durationSec);
}

/** Pola vibrasi per jenis feedback (ms): sukses = getar singkat, gagal = getar panjang. */
export const HAPTIC_PATTERN: Record<'success' | 'error', number[]> = {
  success: [30],
  error: [60, 40, 60],
};

/** Getar perangkat (HP). Tidak berefek / diam di desktop maupun SSR. */
export function haptic(kind: 'success' | 'error'): void {
  if (typeof navigator === 'undefined') return;
  if (typeof navigator.vibrate !== 'function') return;

  navigator.vibrate(HAPTIC_PATTERN[kind]);
}

/** Durasi kedip layar (ms) - dipakai `flashSuccess`/`flashError` dan timer komponen. */
export const FLASH_DURATION_MS = 420;

const FLASH_OVERLAY: Record<'success' | 'error', string> = {
  success: 'pointer-events-none fixed inset-0 z-50 bg-accent-blue',
  error: 'pointer-events-none fixed inset-0 z-50 bg-accent-coral',
};

/**
 * PURE - kelas overlay flash. Komponen disarankan memakai ini (mis. dirender di dalam
 * `AnimatePresence`); dua fungsi imperatif di bawah hanya jalur cepat untuk aksi non-React.
 */
export function flashOverlayClass(kind: 'success' | 'error'): string {
  return FLASH_OVERLAY[kind];
}

function flashOverlay(kind: 'success' | 'error'): void {
  if (typeof document === 'undefined') return;

  const overlay = document.createElement('div');
  overlay.className = flashOverlayClass(kind);
  overlay.setAttribute('aria-hidden', 'true');
  overlay.style.opacity = '0.55';
  overlay.style.transition = `opacity ${FLASH_DURATION_MS}ms ease-out`;

  document.body.appendChild(overlay);

  // Fade-out di frame berikutnya, lalu dilepas supaya tidak menumpuk.
  window.setTimeout(() => {
    overlay.style.opacity = '0';
  }, 0);
  window.setTimeout(() => {
    overlay.remove();
  }, FLASH_DURATION_MS);
}

/** Kedip layar biru (aksi sukses). */
export function flashSuccess(): void {
  flashOverlay('success');
}

/** Kedip layar coral (aksi gagal / scrap). */
export function flashError(): void {
  flashOverlay('error');
}
