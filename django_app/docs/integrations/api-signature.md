# Dokumentasi Simulasi Testing — Endpoint & Signature Lengkap

Berdasarkan `curent_project.json` (v4.3, integrasi I1–I8 selesai), berikut **peta lengkap endpoint + signature** untuk membangun program simulasi E2E.

---

## 1. ENDPOINT — KONTRAK CORE (`config/urls.py`)

### 1.1 Health & Schema

| Method | Path           | Auth | Signature             |
| ------ | -------------- | ---- | --------------------- |
| GET    | `/api/health/` | Anon | `() → {status, time}` |
| GET    | `/api/schema/` | Anon | OpenAPI schema        |
| GET    | `/api/docs/`   | Anon | Swagger UI            |

### 1.2 Metadata (kontrak frontend v2)

| Method | Path                           | Auth            | Response                                                                                                                                                                                                                      |
| ------ | ------------------------------ | --------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| GET    | `/api/v1/metadata/<resource>/` | IsAuthenticated | `{resource:{name,label,id,version}, possible_states:[{id,label,kind}], layout:{sections:[{id,label,fields}]}, field.type ∈ {string,number,boolean,date,enum,reference}, allowed_actions:[{id,label,endpoint}], chatter:bool}` |

Header wajib: `X-Schema-Version`.

### 1.3 Chatter (hanya bundle)

| Method | Path                               | Auth            |
| ------ | ---------------------------------- | --------------- |
| GET    | `/api/v1/chatter/<resource>/<id>/` | IsAuthenticated |

Response: `ChatterPage {preview, total_count, has_more, next_cursor}`

### 1.4 Device

| Method | Path                     | Auth                  | Body                         |
| ------ | ------------------------ | --------------------- | ---------------------------- |
| GET    | `/api/v1/devices/me`     | Cookie `device_token` | —                            |
| POST   | `/api/v1/devices/bind`   | IsAuthenticated       | `{device_code, device_type}` |
| POST   | `/api/v1/devices/unbind` | IsAuthenticated       | `{device_code}`              |

### 1.5 Audit

| Method | Path                                      | Auth            |
| ------ | ----------------------------------------- | --------------- |
| GET    | `/api/v1/audit/products-missing-odoo-id/` | IsAuthenticated |

Response: `{missing:[...], used_in_open_bundles:[...], count}` (dipotong 100).

### 1.6 Rekonsiliasi

| Method | Path                                    | Auth            | Query                                        |
| ------ | --------------------------------------- | --------------- | -------------------------------------------- |
| GET    | `/api/v1/reconciliation/report/?days=N` | IsAuthenticated | `days ∈ 1..90` (default 7, luar range → 400) |

### 1.7 Sync (ERP)

| Method | Path                                              | Auth            | Body                                                                                |
| ------ | ------------------------------------------------- | --------------- | ----------------------------------------------------------------------------------- |
| POST   | `/api/v1/sync/master/<entity>/`                   | IsAuthenticated | 9 entity: `uom, location, warehouse, tax, journal, currency, product, bom, partner` |
| POST   | `/api/v1/sync/odoo/<stage>/`                      | IsAuthenticated | `stage ∈ {WIP, FG}`; resource non-two-stage → 400 + hint                            |
| POST   | `/api/v1/sync/scrap/`                             | IsAuthenticated | sinkron                                                                             |
| GET    | `/api/v1/garmen/orders/{id}/readiness/`           | IsAuthenticated | —                                                                                   |
| POST   | `/api/v1/garmen/orders/{id}/recompute-readiness/` | IsAuthenticated | hanya OrderLine belum READY                                                         |

### 1.8 Print / WA / AI

| Method | Path                        | Auth            | Body                                        |
| ------ | --------------------------- | --------------- | ------------------------------------------- |
| POST   | `/api/v1/print/bundle-tag/` | IsAuthenticated | `{bundle_id}` → 200 + bytes                 |
| POST   | `/api/v1/wa/send`           | IsAuthenticated | stub 200                                    |
| POST   | `/api/v1/ai/chat`           | IsAuthenticated | stub `{ok:false, reason:'not_implemented'}` |

### 1.9 WebSocket

| Path             | Auth                       | Group                                      |
| ---------------- | -------------------------- | ------------------------------------------ |
| `WS /ws/events/` | Anon (⚠️ known limitation) | `bundle.{id}`, `work_order.{id}`, `events` |

---

## 2. ENDPOINT — RESOURCE GARMEN (`/api/v1/garmen/...`)

### 2.1 List / Detail

| Method | Path                              | Response                                                                          |
| ------ | --------------------------------- | --------------------------------------------------------------------------------- |
| GET    | `/api/v1/garmen/bundles/`         | `ListPage {rows, total_count, has_more, next_cursor}` + `allowed_actions` per row |
| GET    | `/api/v1/garmen/bundles/:id/`     | `Bundle` + `allowed_actions`                                                      |
| GET    | `/api/v1/garmen/work-orders/`     | `ListPage`                                                                        |
| GET    | `/api/v1/garmen/work-orders/:id/` | `WorkOrder` + `version` (SHA-256 on-the-fly)                                      |

### 2.2 Action (idempotent)

```
POST /api/v1/garmen/<resource>/<id>/<ACTION_ID>/
Headers: X-Idempotency-Key (opsional, TTL 24 jam)
         X-Conflict-Policy: manual | last_write_wins (default manual)
         X-Force: true  ≡ last_write_wins
Body:    {fields:{...}, version:<optimistic-lock>}
200:     {expected_result:{state, fields}, state, ...} + X-Idempotent-Replay (kalau replay)
409:     {current:{version, state, current_work_center}, conflict:{current:{...}}}
```

**ACTION_ID** (dari metadata): `START`, `FINISH`, `SCRAP`, `REWORK`, `SPLIT`, `MERGE`.

### 2.3 QC resource

```
POST /api/v1/garmen/qc/<id>/<ACTION_ID>/   → ScrapAccumulator, state=RECORDED
```

---

## 3. SIGNATURE SERVICE LAYER (untuk simulasi)

### 3.1 `apps_industry/garment/services/`

```python
# bundle_engine.py
BundleEngine.build(work_order, size_matrix, sku_variant) -> list[Bundle]
# kode bundle: {line_id}-{SIZE}-{seq:03d}, seq reset per size

# overlap_release.py
OverlapReleaseEngine.can_start(bundle, step_no) -> bool   # baca DAG
OverlapReleaseEngine.release_next(bundle) -> list[RoutingStep]

# rework_loop.py
ReworkLoopHandler.handle(bundle, wc_id, defect) -> BundleEvent
# pakai CycleDefinition 'QC_REWORK'

# tag_router.py
TagRouter.route(order) -> ProcessRouting
TagRouter.build_ticket(bundle) -> str   # whitelist placeholder, tanpa eval

# capability_allocator.py
CapabilityAllocator.allocate(step_no, wc_type) -> ProductionLine
# line.capability_tags ⊇ routing_step requirement

# wc_queue.py
WCQueue.queue_depth(wc_id) -> int          # query virtual, bukan tabel
WCQueue.avg_wait_minutes(wc_id) -> float

# two_stage_aggregator.py
TwoStageAggregator.collect_wip(bundle) -> payload   # qty=bundle.qty
TwoStageAggregator.collect_fg(bundle) -> payload    # qty=bundle.qty_done
# TIDAK panggil Odoo — hanya susun payload

# scrap_accumulator.py
ScrapAccumulatorService.record(wc_id, wo_id, scrap_qty, rework_qty, end_loss_qty)
# get_or_create + F() + select_for_update

# priority_scheduler.py
PriorityScheduler.score(order) -> int
# {FAST_TRACK:100, EXPORT:50, CUSTOM:10} + deadline_bonus

# bottleneck_detector.py
BottleneckDetector.scan() -> list[Alert]
# trigger: queue_depth > 10 ATAU avg_wait > 60 menit

# sale_order_sync.py
SaleOrderSyncService.sync(since=None) -> {created, updated, skipped}

# material_readiness.py
MaterialReadinessService.compute(order_line) -> MaterialReadiness
MaterialReadinessService.compute_batch(qs) -> {computed, skipped}
# _fetch_po_data batch; fallback per-line kalau error
# _vendor_bills(): invoice_origin == PO.name; status TERTINGGI + sum amount_total

# scrap_sync.py
ScrapSyncService.collect_pending() -> list[ScrapAccumulator]
ScrapSyncService.sync_one(acc) -> SyncRecord      # stage='SCRAP'
ScrapSyncService.sync_batch() -> {sent, failed, skipped}
# product: acc.bundle.work_order.order_line.product → Product.odoo_id
# UoM: settings.ODOO_UOM_ID (33=PCS); kosong → FAILED

# invoice_sync.py
InvoiceSyncService.enqueue(order) -> SyncRecord   # resource='order', stage='INVOICE'
InvoiceSyncService.sync_one(rec) -> SyncRecord
InvoiceSyncService.sync_pending() -> {sent, failed, skipped}
# PENDING + FAILED attempts<3

# reconciliation.py
ReconciliationService.compare() -> {total_products, alert_count, alerts[:5]}
# 2 RPC: fetch_internal_locations + fetch_stock_quants(child_of=True)
# filter HANYA Product.odoo_id di master
# _mes_bundles(): skip bundle state='DONE' & qty_done=0
ReconciliationService.report(days=7) -> list[StockReconciliation]

# product_audit.py
ProductAuditService.missing_odoo_id() -> list  # max 100
ProductAuditService.used_in_open_bundles() -> list
ProductAuditService.audit() -> dict
```

### 3.2 `integrations/erp_sync/`

```python
# adapters/base.py
class ERPResponse: ok: bool; erp_id: str|None; error: str|None
class ERPAdapterError(Exception): ...
class ERPAdapter:  # bisnis WIP/FG/scrap/invoice
    push_wip_issue(payload) -> ERPResponse
    push_fg_receipt(payload) -> ERPResponse
    push_scrap_wo(payload) -> ERPResponse
    push_customer_invoice_wo(payload) -> ERPResponse
class ERPTransport:  # master data + ping
    ping() -> bool
    fetch_*(...) -> list

# adapters/factory.py
get_adapter() -> ERPAdapter   # fail-safe ke NullAdapter + warning

# adapters/null.py
NullAdapter   # erp_id unik NULL-<uuid4>; semua push no-op OK

# adapters/odoo.py
OdooAdapter.push_wip_issue  → execute_kw('stock.move','create')
OdooAdapter.push_fg_receipt → execute_kw('stock.move','create')
OdooAdapter.push_scrap_wo   → stock.scrap create + action_validate;
                              draft di-unlink best-effort kalau state != done
OdooAdapter.push_customer_invoice_wo → account.move.create
    field: partner_id, move_type='out_invoice', invoice_date, ref, invoice_line_ids
    price_unit=0, TANPA action_post, tanpa journal_id/currency_id

# transport/odoo_transport.py (read-only, fail-safe client None → [])
fetch_uom, fetch_locations, fetch_warehouses, fetch_taxes, fetch_journals,
fetch_currencies, fetch_products, fetch_boms, fetch_partners       # I1
fetch_sale_orders(since, state='sale')
fetch_sale_order_lines(order_ids, since)                           # I2
fetch_purchase_orders(states=('purchase','done'))
fetch_purchase_order_lines(order_ids)                              # I3
fetch_vendor_bills(since, states=('draft','posted'))               # I6
    move_type in ('in_invoice','in_refund'); field += payment_state
fetch_internal_locations()                                         # I7
fetch_stock_quants(location_ids, since, child_of=False)            # I7

# idempotency.py
SyncIdempotency.check(resource, resource_id, stage) -> SyncRecord|None
VALID_STAGES = {'WIP', 'FG', 'SCRAP', 'INVOICE'}
```

### 3.3 `core/`

```python
# event_bus/registry.py
register_listener(event_name, handler_dotted_path)

# Events: BUNDLE_STATE_CHANGED, WORK_ORDER_STATE_CHANGED,
#         SCRAP_RECORDED, ERP_SYNC_COMPLETED

# state_machine
StateMachine.can_transition(state_from, state_to) -> bool  # guard dotted path, fail-closed

# rule_engine
RuleEngine.evaluate(rule, context) -> bool   # tanpa eval/exec, fail-closed

# cycle_handler
CycleInstance(ref_type, ref_id)   # string, core tidak tahu garmen
CycleDefinition 'QC_REWORK'

# idempotency (core)
IdempotencyRecord  # scope=(resource, resource_id, action, request_hash), TTL 24h

# device_profile
DeviceProfileResolver.resolve(request) -> DeviceProfile
# tipe: OPERATOR_HP / KIOSK_TABLET / SCANNER_USB / DESKTOP
```

---

## 4. CELERY TASK REGISTRY

| Task                                          | Trigger                        | Retry              |
| --------------------------------------------- | ------------------------------ | ------------------ |
| `erp_sync.sync_master_*` (9 task)             | beat crontab 02:00             | httpx.HTTPError 3x |
| `erp_sync.sync_sale_orders`                   | beat `*/5`                     | idem               |
| `erp_sync.recompute_readiness`                | beat 04:00                     | idem               |
| `erp_sync.sync_scrap_accumulator`             | beat `0 6,14,22 * * *`         | idem               |
| `erp_sync.sync_invoice`                       | beat `*/15`                    | idem               |
| `erp_sync.reconcile_stock`                    | beat `0 3 * * 1` (Senin)       | idem               |
| `erp_sync.push_wip_issue` / `push_fg_receipt` | endpoint `/sync/odoo/<stage>/` | 3x exp backoff     |

**Total beat: 14 entry.**

---

## 5. ALUR SIMULASI E2E (rekomendasi)

```
[SIM-A] Bootstrap
  1. docker compose build django
  2. docker compose up -d --force-recreate django celery_worker celery_beat
  3. POST /api/v1/sync/master/product/  (x9 master)
  4. GET  /api/v1/audit/products-missing-odoo-id/  → pastikan []

[SIM-B] Order → Invoice
  POST /api/v1/sync/master/... (partner, product, bom)
  → SaleOrderSyncService.sync()
  → BundleEngine.build()
  POST /api/v1/garmen/bundles/{id}/START/     (WIP)
  POST /api/v1/garmen/bundles/{id}/FINISH/    (FG)
  → WO DONE (atau CANCELLED) → listener enqueue INVOICE
  POST /api/v1/sync/odoo/WIP/ + /FG/  → cek SyncRecord

[SIM-C] Rework + Scrap
  POST /api/v1/garmen/bundles/{id}/REWORK/
  POST /api/v1/garmen/qc/{id}/RECORD/
  POST /api/v1/sync/scrap/

[SIM-D] Readiness + Vendor Bill
  GET  /api/v1/garmen/orders/{id}/readiness/   → 11 kunci
  POST /api/v1/garmen/orders/{id}/recompute-readiness/
  → pastikan vendor_bill_status ∈ {NONE,DRAFT,POSTED,PAID}

[SIM-E] Reconciliation
  GET /api/v1/reconciliation/report/?days=7
  → cek alert_count & StockReconciliation rows (append-only)

[SIM-F] Failsafe (ERP_ADAPTER=null)
  → semua push harus SENT dengan erp_id NULL-<uuid4>
  → bundle action tetap 200 + BundleEvent tercatat

[SIM-G] Load test
  LOAD_TEST=1 pytest tests/integration/test_load_1000.py
```

---

## 6. CHECKLIST IDEMPOTENSI (wajib di simulator)

| Skenario                                | Expected                                |
| --------------------------------------- | --------------------------------------- |
| Replay `X-Idempotency-Key` sama         | 200 + header `X-Idempotent-Replay`      |
| Replay `/sync/odoo/WIP/` 2x             | `SyncRecord` tetap 1                    |
| Replay push WIP 1000 bundle 2 fase      | tetap 1000 (bukan 2000)                 |
| Conflict tanpa header                   | 409 body `current` + `conflict.current` |
| `X-Force: true`                         | lewati 409                              |
| Resource non-two-stage di `/sync/odoo/` | 400 + hint `/api/v1/sync/scrap/`        |
| Anon ke endpoint sync/audit             | 403                                     |
| `days=0` atau `days=91`                 | 400 tanpa panggil service               |

---

## 7. YANG BELUM ADA (jangan disimulasikan dulu)

- `POST /api/v1/ai/chat` → masih stub `{ok:false}`
- `WS /ws/events/` → ChatterBox belum di-wire; auth masih AllowAny
- `POST /api/v1/wa/send` → MockWAGateway
- Vendor bill linkage (`invoice_origin`) → kosong di seed instance
- Frontend v2: WS real-time, device-binding UI, tombol kupon

---

Mau saya lanjutkan jadi **skeleton kode simulator** (Python + httpx + pytest, atau Node + bun test) berdasarkan peta di atas?
