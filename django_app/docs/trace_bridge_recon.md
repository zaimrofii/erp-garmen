# Trace Bridge — Recon (request_id propagation)

Recon saja, tanpa perubahan kode.

**A. Apakah `JsonFormatter` menulis field `request_id`? Ya.**
`config/logging.py` baris 75–77: `getattr(record, "request_id", None)`; kalau ada
diisi ke `payload["request_id"]`.

**B. Apakah `RequestIDMiddleware` menyimpannya ke thread/context yang bisa dibaca formatter? Ya.**
Nilai disimpan di **thread-local** `_local.request_id` (`config/middleware.py`
L35–45). Middleware memanggil `set_request_id()` (L67) dan membersihkannya di
`finally` (L72). `RequestIDFilter` (L77–84) menyalin `get_request_id()` ke
`record.request_id`, yang dibaca JsonFormatter. Karena thread-local, hanya
berlaku di thread request — bukan di worker Celery.

**C. Apakah `_push_stage` memanggil `.apply_async()` atau `.delay()`? Ada `headers=`?**
`_push_stage` hanyalah helper sinkron (tidak meng-enqueue). Enqueue ada di
`integrations/erp_sync/api.py` L244: `task.delay(resource, resource_id, payload,
record.pk)` — memakai **`.delay()`**, bukan `.apply_async()`, dan **tidak ada
`headers=`**. Jadi `request_id` TIDAK diteruskan ke task.

**D. Apakah `RotatingFileHandler` sudah punya `maxBytes` + `backupCount`? Tidak.**
`settings.LOGGING` hanya punya handler `console` = `logging.StreamHandler`
(L505–511). Tidak ada RotatingFileHandler/FileHandler; `maxBytes`/`backupCount`
tidak ditemukan di seluruh sumber.
