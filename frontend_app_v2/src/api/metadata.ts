// ADAPTER - RE-EXPORT saja, TANPA logic domain.
//
// Halaman HANYA boleh mengimpor dari `@/api/metadata` - JANGAN dari `./real/*`.
// Implementasi ada di `api/real/metadata.ts` (MODE.metadata === 'real').
export * from './real/metadata';
