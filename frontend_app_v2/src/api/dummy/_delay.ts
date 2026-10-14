/**
 * @dummy - helper latensi BERSAMA untuk seluruh fixture di folder `api/dummy/`.
 * (Bukan fixture; tidak mewakili endpoint mana pun.)
 *
 * Setiap fungsi dummy WAJIB menunggu 100-300 ms supaya UI Fase 15+ sudah terbiasa
 * dengan latensi network nyata:
 *
 *     await delay(100 + Math.random() * 200);
 */

/** Batas bawah latensi simulasi (ms). */
export const MIN_DELAY_MS = 100;

/** Batas atas latensi simulasi (ms). */
export const MAX_DELAY_MS = 300;

export function delay(ms: number): Promise<void> {
  return new Promise<void>((resolve) => {
    setTimeout(resolve, ms);
  });
}
