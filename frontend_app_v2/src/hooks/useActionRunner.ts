/**
 * useActionRunner.ts — wrapper tipis `submitAction` untuk ActionButton (Fase 4).
 *
 * `SubmitActionInput` butuh `queue: OfflineQueue` → belum bisa dipanggil di halaman;
 * Fase 7 (Workshop) akan inject OfflineQueue. Untuk sekarang hanya re-export tipe +
 * fungsi aslinya supaya Fase 4 bisa compile tanpa `any`.
 */
export type { SubmitActionInput, SubmitActionResult } from '@/lib/action-runner';
export { submitAction } from '@/lib/action-runner';
