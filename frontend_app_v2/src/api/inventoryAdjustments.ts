// ADAPTER - RE-EXPORT saja, TANPA logic domain (Inventory Adjustment, H2.5).
//
// Halaman/hook HANYA boleh mengimpor dari `@/api/inventoryAdjustments` - JANGAN dari
// `./real/*`. Implementasi ada di `api/real/inventoryAdjustments.ts`
// (MODE.inventoryAdjustments === 'real' di `api/_adapter.ts`).
//
// CATATAN: `@/api/inventory` (B7: `GET /inventory/products/`) & adapter reporting B30
// TETAP ada dan tidak diubah; barrel ini khusus LOG adjustment H2.5 + pembacaan
// stok on-demand.
export * from './real/inventoryAdjustments';
