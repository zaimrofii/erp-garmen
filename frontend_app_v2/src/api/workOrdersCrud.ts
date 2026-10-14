// ADAPTER - RE-EXPORT saja, TANPA logic domain (Work Order CRUD, H2.3).
//
// Halaman/hook HANYA boleh mengimpor dari `@/api/workOrdersCrud` - JANGAN dari
// `./real/*`. Implementasi ada di `api/real/workOrdersCrud.ts`
// (MODE.workOrdersCrud === 'real' di `api/_adapter.ts`).
//
// CATATAN: `@/api/workOrders` (F13: list+detail tipis) TETAP ada & tidak diubah;
// barrel ini membawa CRUD H2.3 (create/update/delete/split/generate + aksi state).
export * from './real/workOrdersCrud';