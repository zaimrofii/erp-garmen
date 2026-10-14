// ADAPTER - RE-EXPORT saja, TANPA logic domain.
//
// Halaman/hook HANYA boleh mengimpor dari `@/api/workOrders` - JANGAN dari
// `./real/*` atau `./dummy/*`. Implementasi ada di `api/real/workOrders.ts`
// (MODE.workOrders === 'real' di `api/_adapter.ts`).
//
// Kalau nanti perlu fallback dummy, ganti baris re-export di bawah dengan pola
// `pickAdapter` (lihat `api/dashboard.ts` sebagai contoh).
export * from './real/workOrders';
