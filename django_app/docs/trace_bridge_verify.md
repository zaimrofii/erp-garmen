# Trace Bridge — Verifikasi CLI (Step 6)

Dijalankan `cd django_app && python -m trace_bridge.api &`, tunggu 2 detik.
Catatan: `python` tidak ada di PATH WSL → dipakai `venv/bin/python` (setara).

## request_id dipakai
`grep -o '"request_id": "[^"]*"' logs/mes.jsonl | tail -1`
→ **trace-bundle-e2e-70cf5659** (dari E2E test Bagian A).

## curl endpoint
`curl -s http://127.0.0.1:8765/_ai/trace/trace-bundle-e2e-70cf5659 | python -m json.tool`

Ringkas (8 span, duration_ms=130, errors=0):
- `core.state_machine.services:execute_transition` (0 ms)
- `apps_industry.garment.api.actions.executor:execute` (109 ms)
- `core.audit.services:log` (2 ms, 1 ms)
- `core.idempotency.services:save` (4 ms, 5 ms)
- `integrations.erp_sync.idempotency:get_or_create_sync_record` (7 ms)
- `integrations.erp_sync.api:post` (0 ms)

## Status HTTP
- `GET /_ai/trace/trace-bundle-e2e-70cf5659` → **200**
- `GET /_ai/trace/tidak-ada-xyz` → **404**

## Catatan
- Span `integrations.erp_sync.*` (api:post = enqueue + idempotency) terlihat → korelasi request → ERP sync terbukti.
- Aksi bundle sendiri hanya menghasilkan span `core.*`/`apps_industry.*`; span `erp_sync` datang dari two-stage sync pada request id yang sama.
- `errors: 0` karena tak ada baris level WARNING/ERROR di trace ini.
- Server dimatikan setelah verifikasi; port 8765 bebas.
