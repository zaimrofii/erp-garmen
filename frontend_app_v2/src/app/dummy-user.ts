/**
 * dummy-user.ts - identitas user sementara sampai auth nyata.
 *
 * // @dummy - ganti dengan data dari `/devices/me` atau `/users/me` setelah auth endpoint siap.
 *
 * Nama & inisial di sini hanya untuk tampilan (TopBar user pill). Label role TIDAK
 * diambil dari sini - dipakai `ROLE_LABELS[useRole()]` supaya konsisten dengan
 * sidebar yang difilter per role.
 */

export interface CurrentUser {
  name: string;
  role: string;
  initials: string;
}

export const DUMMY_USER: CurrentUser = {
  name: 'Budi Santoso',
  role: 'Supervisor Produksi',
  initials: 'BS',
};
