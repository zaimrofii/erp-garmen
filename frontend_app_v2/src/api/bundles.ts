// ADAPTER - RE-EXPORT saja, TANPA logic domain.
//
// Halaman/hook HANYA boleh mengimpor dari `@/api/bundles` - JANGAN dari `./real/*`
// atau `./dummy/*`. Implementasi real ada di `api/real/bundles.ts`
// (MODE.bundles === 'real' di `api/_adapter.ts`).
//
// Kalau nanti perlu fallback dummy untuk resource ini, ganti baris re-export di bawah
// dengan pola `pickAdapter` (lihat `api/dashboard.ts` sebagai contoh).
export * from './real/bundles';
