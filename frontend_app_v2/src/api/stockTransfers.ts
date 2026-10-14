// ADAPTER - RE-EXPORT saja, TANPA logic domain (Stock Transfer, H2.6).
//
// Halaman/hook HANYA boleh mengimpor dari `@/api/stockTransfers` - JANGAN dari
// `./real/*`. Implementasi ada di `api/real/stockTransfers.ts`
// (MODE.stockTransfers === 'real' di `api/_adapter.ts`).
//
// CATATAN: `@/api/inventory` (B7), reporting B30, dan H2.5
// (`@/api/inventoryAdjustments`) TETAP ada dan tidak diubah.
export * from './real/stockTransfers';
