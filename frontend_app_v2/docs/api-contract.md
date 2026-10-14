## 📄 File 2 — `frontend_app_v2/docs/api-contract.md`

> **Catatan:** File ini **PANJANG (~600 baris)**. Karena tidak muat di chat ini, **salin dari Repomix yang kau kirim ke saya tadi** — cari blok `<file path="api-contract.md">` di pesan sebelumnya. Isinya lengkap dari situ.

**Atau**, kalau mau versi ringkas (cukup untuk dev), pakai ini:

```markdown
# API Contract — MES Garmen (Ringkas)

> Versi lengkap ada di `frontend_app_v2/docs/api-contract.md` (dari Repomix).
> Update terakhir: F7.1 (2026-10-10).

## Base URL

- Dev: `http://localhost:8000`
- Prod: `https://<domain>`
- Prefix: `/api/v1/`

## Auth

- Login: `POST /api/v1/auth/login/` (username+password) → session cookie
- Login operator: `POST /api/v1/auth/login-operator/` (kode 4 digit)
- Device bind: `POST /api/v1/devices/bind/` → cookie `device_token`
- Device me: `GET /api/v1/devices/me/`
- Me: `GET /api/v1/auth/me/`

## Resource Pattern

- List: `GET /api/v1/garmen/{resource}/` → `{rows, total_count, has_more, next_cursor}`
- Detail: `GET /api/v1/garmen/{resource}/{id}/`
- Action: `POST /api/v1/garmen/{resource}/{id}/{ACTION_ID}/`

## Endpoint Agregat (F1–F3A — 23 total)

| Group      | Endpoint                                | Method              |
| ---------- | --------------------------------------- | ------------------- |
| Dashboard  | `/api/v1/dashboard/summary/`            | GET                 |
| Production | `/api/v1/production/buffer-queue/`      | GET                 |
| Production | `/api/v1/routing/graph/`                | GET                 |
| Quality    | `/api/v1/quality/defects/`              | GET / POST          |
| Quality    | `/api/v1/quality/aql/`                  | GET                 |
| Quality    | `/api/v1/quality/rework/`               | GET                 |
| Inventory  | `/api/v1/inventory/products/`           | GET                 |
| Inventory  | `/api/v1/inventory/operations/`         | GET                 |
| Purchase   | `/api/v1/purchase/orders/`              | GET                 |
| Purchase   | `/api/v1/purchase/reporting/`           | GET                 |
| Purchase   | `/api/v1/purchase/vendors/`             | GET                 |
| Reports    | `/api/v1/reports/line-efficiency/`      | GET                 |
| Reports    | `/api/v1/reports/wip/`                  | GET                 |
| Reports    | `/api/v1/reports/lead-time/`            | GET                 |
| Reports    | `/api/v1/reports/on-time-delivery/`     | GET                 |
| Settings   | `/api/v1/settings/routing/`             | GET+POST            |
| Settings   | `/api/v1/settings/bundling/`            | GET+POST            |
| Settings   | `/api/v1/settings/line-allocation/`     | GET+POST            |
| Settings   | `/api/v1/settings/users/`               | GET+POST+PUT+DELETE |
| Settings   | `/api/v1/settings/roles/`               | GET                 |
| Settings   | `/api/v1/settings/devices/`             | GET                 |
| AI         | `/api/v1/ai/hitl/queue/`                | GET                 |
| AI         | `/api/v1/ai/hitl/{id}/approve\|reject/` | POST                |

## Sync ERP

- `POST /api/v1/sync/odoo/{WIP|FG}/`
- `POST /api/v1/sync/master/{entity}/`
- `POST /api/v1/sync/scrap/`

## Print / WA / AI

- `POST /api/v1/print/bundle-tag/`
- `POST /api/v1/print/kupon/`
- `POST /api/v1/wa/send/` (stub)
- `POST /api/v1/ai/chat` (stub)

## Header Penting

- `X-CSRFToken` (POST)
- `X-Idempotency-Key` (opsional)
- `X-Base-Version` (optimistic lock)
- `X-Conflict-Policy: manual | last_write_wins`
- `X-Force: true`

## Error

- 400 bad request · 401 unauth · 403 forbidden · 404 not found · 409 conflict · 429 rate limit

## ListPage Envelope

`{rows, total_count, has_more, next_cursor}`

## Referensi Lengkap

- `django_app/docs/blueprint.md` §7b (23 endpoint)
- `django_app/docs/integration-config.md` §7
- OpenAPI: `GET /api/schema/` + `GET /api/docs/`
```
