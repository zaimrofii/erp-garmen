// ADAPTER - RE-EXPORT saja, TANPA logic domain.
//
// Halaman/hook HANYA boleh mengimpor dari `@/api/orderLines` - JANGAN dari `./real/*`.
// Implementasi ada di `api/real/orderLines.ts` (MODE.orderLines === 'real').
//
// F1 (D7): resource kanonik = `order-lines` (`/garmen/order-lines/`), BUKAN `orders`.
// Pengecualian: readiness Order tetap `/garmen/orders/{id}/readiness/` (lihat real/orderLines.ts).
export * from './real/orderLines';
