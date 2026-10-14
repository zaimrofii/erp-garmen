# Trace Bridge — jejak satu request lintas HTTP → Celery → log

Menyatukan log satu `request_id` (request HTTP) dengan log task Celery yang
dipicu request itu, dibaca dari file JSONL — tanpa OTel/Loki.

## 1. Alur

```
HTTP (X-Request-ID) → config.middleware.RequestIDMiddleware (thread-local)
   → SyncOdooView: task.apply_async(headers={"x-request-id": rid})
   → worker: tasks._bind_request_id (set_request_id) → log JSONL
   → logs/mes.jsonl (RotatingFileHandler, 1 baris = 1 JSON)
   → trace_bridge/reader.read_trace(rid, Path("logs"))
   → trace_bridge/normalize.to_spans(rows, rid)
   → trace_bridge/api.py   GET /_ai/trace/{trace_id}
   → Cline / CLI (curl | python -m json.tool)
```

## 2. Menjalankan

```
cd django_app && python -m trace_bridge.api        # http://127.0.0.1:8765
curl -s http://127.0.0.1:8765/_ai/trace/<id> | python -m json.tool
```

## 3. Kontrak output (`normalize.to_spans`)

```json
{"trace_id": str, "duration_ms": int,
 "spans": [{"name": str, "ms": int, "error": str (opsional)}], "errors": int}
```

`name` = `<logger>:<funcName>`; key `error` ada bila level WARNING/ERROR/CRITICAL.

## 4. Konfigurasi (`trace_bridge/config.yaml`, override env `TRACE_BRIDGE_<KEY>`)

`log_dir`, `log_basename`, `max_backups`, `max_spans`, `max_lines`, `host`, `port`
(contoh: `TRACE_BRIDGE_PORT=9000`).

## 5. Troubleshooting

- Log kosong → `log_dir` relatif; jalankan dari `django_app/`.
- `request_id` "-" → klien tidak mengirim header `X-Request-ID`.
- Worker tanpa `request_id` → restart worker (agar `tasks.py` baru dimuat).
- Trace tidak ada → cek rotasi `logs/mes.jsonl.1`, `.2`, … (reader membacanya).

## 6. Known gap (dari temuan Step 5)

Aksi **bundle** TIDAK memicu ERP sync: `BUNDLE_STATE_CHANGED` tidak punya
listener. Jadi trace hanya mencakup sync yang dipicu manual/endpoint/beat.
Perbaikan = tambah listener di `core.event_bus` (di luar scope Trace Bridge).

## 7. Yang TIDAK boleh

Tanpa OTel/Loki/LLM, tanpa endpoint tambahan, dan JANGAN baca level < INFO.

## MENJALANKAN LEWAT Cline/AI

Cline cukup:

text
Baca http://127.0.0.1:8765/_ai/trace/<id> dan jelaskan kenapa gagal.
Kontrak JSON sudah stabil (blueprint §4), jadi tidak perlu prompt panjang.
