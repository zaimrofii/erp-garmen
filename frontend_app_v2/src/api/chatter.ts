// ADAPTER - RE-EXPORT saja, TANPA logic domain.
//
// Halaman/hook HANYA boleh mengimpor dari `@/api/chatter` - JANGAN dari `./real/*`
// atau `./dummy/*`. Implementasi ada di `api/real/chatter.ts` (REST lewat api-client
// + helper real-time `integrations/ws-chatter.ts`).
export * from './real/chatter';
