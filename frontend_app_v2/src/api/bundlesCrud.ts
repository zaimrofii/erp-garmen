// ADAPTER - RE-EXPORT saja, TANPA logic domain (Bundle CRUD, H2.4).
//
// Halaman/hook HANYA boleh mengimpor dari `@/api/bundlesCrud` - JANGAN dari
// `./real/*`. Implementasi ada di `api/real/bundlesCrud.ts`
// (MODE.bundlesCrud === 'real' di `api/_adapter.ts`).
//
// CATATAN: `@/api/bundles` (F13: list/detail tipis + `submitBundleAction` untuk aksi
// state machine) TETAP ada & tidak diubah; barrel ini membawa CRUD H2.4
// (create/preview/update/delete/split/merge).
export * from './real/bundlesCrud';