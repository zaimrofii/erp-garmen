    # `docs/uat/02-test-data.md` — Data Seed & Cara Reset

    ```markdown
    # 02 — Test Data UAT

    > **Berlaku:** 2026-10-27 · **Versi:** 1.0
    > **Prinsip:** Data uji harus **tetap, idempoten, dan punya alasan**. Tidak ada data asal.

    ---

    ## 1. Seed Command

    | Command | Fungsi | Idempoten | Marker |
    |---|---|---|---|
    | `seed_big_test` | Seed masif (50 order, 100 WO, 200 bundle, dll) — **dipakai UAT** | ✅ | `BIG TEST 2026-10` / `SO-DEMO`/`WO-DEMO`/`BND-DEMO`/`INV-DEMO`/`PO-DEMO`/`PAY-DEMO` |
    | `seed_rich_garment` | Seed master + 10 order + anomali operator | ✅ | `UAT DEMO 2026-10` |
    | `seed_demo_llm` | Seed AI demo (PT Demo Fashion, 3 order, HITL) | ✅ | `DEMO-LLM-*` |
    | `aggregate_daily` | Hitung snapshot metrik harian | ✅ | — |
    | `seed_demo_polos` | Produk demo polos (6 produk unik) | ✅ | ODOO-64..69 |

    **Urutan UAT:**
    ```bash
    python manage.py seed_big_test      # utama
    python manage.py seed_rich_garment  # master + operator anomali
    python manage.py aggregate_daily    # snapshot metrik
    ```

    `seed_big_test` sudah memanggil `seed_rich_garment` + `seed_documents` di dalamnya (lihat `current_project.json` `seed_big_test.command`). Jalankan `seed_big_test` saja cukup, tapi `seed_rich_garment` eksplisit aman (idempoten).

    ---

    ## 2. Isi Data (dari `seed_big_test`)

    ### 2.1 Volume (fresh DB)
    | Entitas | Jumlah | Catatan |
    |---|---|---|
    | Order | 50 | 20 EXPORT / 20 CUSTOM / 10 BRAND; 30 DONE / 10 CONFIRMED / 5 IN_PROGRESS / 5 DRAFT |
    | Work Order | 100 | — |
    | Bundle | 200 | termasuk bundle SEWING-2 buffer tinggi |
    | BundleEvent | 833 | termasuk 237 dengan `work_center_code` (backfill) |
    | ScrapAccumulator | 52 | SEWING-2 naik 7 hari; rework QC-1 dominan; shift 2 ~30% |
    | CustomerInvoice | 50 | — |
    | PurchaseOrder | 20 | — |
    | VendorBill | 20 | — |
    | Payment | 30 | INBOUND + OUTBOUND |
    | JournalEntry | 10 | double-entry, balance |
    | InventoryAdjustment | 10 | — |
    | StockTransfer | 10 | — |
    | AIDecisionLog | 50 | termasuk 148 test scope |
    | AIHitlQueue | 10 | 5 PENDING / 3 APPROVED / 2 REJECTED |
    | AISemanticCache | 20 | — |
    | DailySummary | 30 | — |
    | Document (SOP) | 8 | — |
    | Operator | 6 | 2 mencurigakan (op-andi, op-budi) |
    | SyncRecord | 50 order + 50 invoice | status SENT + `erp_id` terisi |
    | Master: Line / WC / Routing / Product / BOM / Partner | 3 / 8 / 2 / 8 / 4 / 6 | — |

    ### 2.2 Pola Sengaja (untuk uji laporan & AI)
    | Pola | Dipakai di Sesi |
    |---|---|
    | Scrap SEWING-2 naik 7 hari | 4 (laporan scrap), 5 (AI "kenapa scrap naik?") |
    | Rework QC-1 dominan | 3 (rework loop), 4 (laporan produksi) |
    | Shift 2 ~30% | 4 (korelasi shift) |
    | Bundle SEWING-2 buffer tinggi | 3 (buffer queue), 4 (WIP report) |
    | Operator `op-andi`/`op-budi` phantom (32-35 event/30 mnt) + impossible cycle (20 dtk) + scrap 3/10 | 5 (AI anomaly) |
    | Order `DEMO-LLM-LATE-01` late 5 hari | 4 (OTD report), 5 (AI "bundle paling lambat?") |

    ### 2.3 Rentang Data
    - Event produksi: **2026-10-08 .. 2026-10-21**
    - Scrap Des 2025 = **0** (untuk uji Q28 "scrap Des 2025" → jawaban "tidak ada")
    - Scrap all-time = 262

    ---

    ## 3. Kredensial UAT

    ### 3.1 Akun 7 Role
    | Role | Username | Password | Catatan |
    |---|---|---|---|
    | admin | `admin` | `Admin12345!` | akses `/settings/*` |
    | owner | `owner` | `Owner12345!` | semua akses |
    | supervisor | `supervisor` | `Sup12345!` | reports, HITL |
    | qc | `qc1` | `Qc12345!` | form QC |
    | operator | `op-andi` | `demo12345` | kode 4 digit (login-operator) |
    | operator bersih | `op-citra` | `demo12345` | untuk kontrol (bukan anomali) |
    | inventory | `inventory` | `Inv12345!` | adjustment, transfer |
    | purchasing | `purchasing` | `Purch12345!` | PO, vendor bill |
    | finance | `finance` | `Fin12345!` | invoice, payment, JE |

    **Operator login pakai kode 4 digit** via `/api/v1/auth/login-operator` — kode tertera di profil operator (dari seed). Cek:
    ```bash
    docker compose exec django python manage.py shell -c \
    "from core_auth.models import User; print([(u.username, getattr(u,'operator_code',None)) for u in User.objects.filter(role__name='operator')])"
    ```

    ### 3.2 Akun Odoo
    | Peran | Kredensial | Dipakai |
    |---|---|---|
    | Admin Odoo staging | (dari klien) | fix `stock.group_stock_manager` |
    | `api_bot` (user API) | (dari klien) | sync MES → Odoo |

    ### 3.3 Device
    | Device | Bind ke | Tujuan |
    |---|---|---|
    | HP-01 | `op-andi` | Sesi 3 offline test |
    | Kios-01 | `qc1` | Sesi 3 rework |
    | Scanner-01 | `supervisor` | Sesi 3 kanban (opsional) |

    ---

    ## 4. Data Uji Tetap (Referensi Skenario)

    Kode di bawah **wajib ada** setelah seed — dipakai di `03-skenario.md`. Bila tidak ada, seed gagal / data korup.

    ### 4.1 Master
    | Kode | Entitas | Alasan keberadaan |
    |---|---|---|
    | `PRD-UAT-001` | Product (Kaos Polos, cost 50.000, sale 75.000) | Uji HPP & margin H4.4 |
    | `PRD-UAT-002` | Product (cost 0) | Uji `missing_cost` H4.4 |
    | `CUST-UAT-01` | Partner customer | Uji SO |
    | `VEND-UAT-01` | Partner vendor | Uji PO |
    | `BOM-UAT-001` | BOM | Uji validasi siklus |
    | `WC-UAT-SEW` | Work Center | Uji routing |
    | `WC-UAT-QC` | Work Center | Uji rework |
    | `RT-UAT-01` | Routing SEW → QC → PACK | Uji DAG + rework loop |
    | `TAX-PPN11` | Tax PPN 11% | Uji invoice |
    | `CUR-IDR` | Currency default | Uji guard delete |

    ### 4.2 Transaksi
    | Kode | Entitas | Alasan |
    |---|---|---|
    | `SO-UAT-001` | Sales Order (3 line, qty 10/20/30) | Uji generate WO |
    | `PO-UAT-001` | Purchase Order (vendor VEND-UAT-01) | Uji push Odoo |
    | `WO-UAT-001` | Work Order | Uji split |
    | `BND-UAT-001..003` | Bundle | Uji scan, split/merge |
    | `INV-UAT-001` | Customer Invoice | Uji payment |
    | `VB-UAT-001` | Vendor Bill | Uji bill |
    | `PAY-UAT-001` | Payment INBOUND | Uji anti-overpay |
    | `JE-UAT-001` | Journal Entry (2 baris balance) | Uji double-entry |

    ### 4.3 Produksi
    | Kode | Entitas | Alasan |
    |---|---|---|
    | `BND-DEMO-01` | Bundle state READY | Uji scan MULAI |
    | `BND-DEMO-LATE-01` | Bundle late 5 hari | Uji AI "paling lambat" |
    | `SO-DEMO-LATE-01` | Order deadline lewat | Uji OTD |
    | Scrap 5 baris di `WC-UAT-SEW` | ScrapAccumulator | Uji laporan scrap & alert |

    ### 4.4 AI & Anomali
    | Kode | Entitas | Alasan |
    |---|---|---|
    | `op-andi` | Operator phantom | Uji AI anomaly |
    | `op-budi` | Operator phantom | Uji AI anomaly |
    | `DEMO-LLM-LATE-01` | Order late | Uji AI lead time |
    | `G024` | op-eka 17 event FINISH Okt 2026 | Uji golden set AI |
    | `G026` | customer aktif = 25 | Uji count customer |
    | `G028` | scrap Des 2025 = 0 | Uji "tidak ada data" |

    ---

    ## 5. Verifikasi Invariants (WAJIB Sebelum Sesi)

    ### 5.1 Invariants Data
    ```bash
    docker compose exec django python manage.py shell -c \
    "from ai_agent.data_access.invariants import check_all; print(check_all())"
    ```

    **Harapan setelah seed bersih:**
    ```python
    {'A': 0, 'B': 0, 'C': 0, 'D': 0, 'E': 0, 'F': 4}
    ```

    | Kode | Arti | Target |
    |---|---|---|
    | A | Order line qty ≤ 0 | 0 |
    | B | Order line harga 0 (kecuali known) | 0 |
    | C | Bundle tanpa WO | 0 |
    | D | Order line tanpa product_id | 0 |
    | E | Scrap negatif | 0 |
    | **F** | **Grup duplikat nama+harga** | **4 (diketahui)** |

    **F=4 pengecualian:** Kaos Lapangan x6 (ODOO-73/74/75/81/82/83) + Kaos Polos Premium/Cotton Combed 30s/Putih Dewasa V2 masing-masing x2. Butuh **keputusan bisnis** (merge/hapus), bukan bug. Dicatat di `05-defect-log.md` sebagai DATA.

    ### 5.2 Verifikasi Cepat Angka Kunci
    ```bash
    # G024: op-eka event FINISH Okt 2026
    docker compose exec django python manage.py shell -c "
    from apps_industry.garment.models import BundleEvent
    print('op-eka FINISH:', BundleEvent.objects.filter(actor__username='op-eka', event_type='BUNDLE_FINISH', ts__year=2026, ts__month=10).count())
    "
    # harapan: 17

    # G026: customer aktif
    docker compose exec django python manage.py shell -c "
    from master.models import Partner
    print('customer aktif:', Partner.objects.filter(is_customer=True, is_active=True).count())
    "
    # harapan: 25

    # G028: scrap Des 2025
    docker compose exec django python manage.py shell -c "
    from apps_industry.garment.models import ScrapAccumulator
    from datetime import date
    print('scrap Des 2025:', ScrapAccumulator.objects.filter(created_at__year=2025, created_at__month=12).count())
    "
    # harapan: 0
    ```

    Bila angka beda → **jangan lanjut sesi**. Diagnosis seed dulu.

    ### 5.3 Verifikasi Idempotensi
    ```bash
    # Jalankan seed 2x, count harus sama
    docker compose exec django python manage.py seed_big_test
    docker compose exec django python manage.py shell -c "
    from apps_industry.garment.models import Order, Bundle
    print('orders:', Order.objects.count(), 'bundles:', Bundle.objects.count())
    "
    docker compose exec django python manage.py seed_big_test
    docker compose exec django python manage.py shell -c "
    from apps_industry.garment.models import Order, Bundle
    print('orders:', Order.objects.count(), 'bundles:', Bundle.objects.count())
    "
    # harapan: count IDENTIK setelah run ke-2
    ```

    Bila count berubah → seed **tidak idempoten** = BUG-CRITICAL (data dobel di produksi).

    ---

    ## 6. Reset Antar-Sesi

    ### 6.1 Kapan Reset
    | Situasi | Reset? |
    |---|---|
    | Awal setiap sesi | ✅ reset seed (cepat) |
    | Setelah BUG-CRITICAL fix | ✅ reset penuh |
    | Antar klien A → B | ✅ reset penuh + env terpisah |
    | Ingin ulang 1 skenario | ❌ cukup ulang skenario (seed idempoten) |

    ### 6.2 Opsi Reset
    ```bash
    # Opsi A — reset penuh (bersih ~3 menit)
    docker compose down -v && docker compose up -d
    docker compose exec django python manage.py migrate
    docker compose exec django python manage.py seed_big_test
    docker compose exec django python manage.py aggregate_daily

    # Opsi B — reset seed saja (cepat ~30 detik)
    docker compose exec django python manage.py seed_big_test
    docker compose exec django python manage.py aggregate_daily
    ```

    Setelah reset apa pun → **verifikasi invariants §5.1**.

    ### 6.3 Reset Cache & AI
    ```bash
    # Cache AI (semantic cache + memory)
    docker compose exec django python manage.py shell -c \
    "from django.core.cache import cache; cache.clear()"

    # Pending clarification state (R1-R3)
    docker compose exec django python manage.py shell -c \
    "from django.core.cache import cache; [cache.delete(k) for k in cache.keys('clarify:*')]"
    ```

    Cache dibersihkan bila: AI jawaban aneh (cache hit stale), HITL queue tidak muncul, pending state nyangkut.

    ---

    ## 7. Data yang TIDAK Boleh Diubah Saat UAT

    | Data | Alasan |
    |---|---|
    | `op-andi` / `op-budi` phantom event | Uji AI anomaly — ubah = AI tidak menemukan anomali |
    | Scrap Des 2025 = 0 | Uji "tidak ada data" — isi = Q28 lolos palsu |
    | G024 op-eka = 17 FINISH | Golden set — ubah = AI dinilai salah |
    | Bundle `BND-DEMO-LATE-01` | Uji AI lead time |
    | `stock.group_stock_manager` di Odoo | Tech debt — fix **hanya** oleh admin Odoo, bukan kode MES |

    Bila perlu ubah → **catat** di `04-hasil/` + `05-defect-log.md` + reset setelah sesi.

    ---

    ## 8. Data yang Boleh Dibuat Saat UAT

    Tester **boleh** membuat data baru (CRUD) untuk menguji alur, asal:
    1. Pakai prefix `UAT-` (mis. `UAT-PRD-01`, `UAT-SO-01`) agar mudah dibersihkan
    2. Tidak menimpa data tetap §4
    3. Reset setelah sesi bila mengganggu sesi berikutnya

    ---

    ## 9. Referensi

    | Dokumen | Kegunaan |
    |---|---|
    | `01-environment.md` | Setup staging + env var |
    | `03-skenario.md` | Skenario memakai kode data §4 |
    | `current_project.json` `seed_big_test` | Definisi lengkap seed |
    | `fase_data_cleanup_2026-10-22` | Riwayat pembersihan (F=4 pengecualian) |
    | `fase_golden_set_2026-10-22` | Verifikasi G024/G026/G028 |
    | `django_app/docs/runbook-operasional.md` | Troubleshooting seed |
    ```

    ---

    **Yang perlu Anda isi:**
    - **§3.2 kredensial Odoo staging** — dari klien
    - **§3.1 verifikasi password** — jalankan shell command untuk cek `operator_code` operator; sesuaikan bila kode 4 digit beda dari seed
    - **§3.3 nama device aktual** — setelah bind

    **Yang saya ambil dari kondisi nyata:**
    - Volume persis dari `seed_big_test` di `current_project.json`
    - Pola sengaja (SEWING-2 naik, op-andi phantom, DEMO-LLM-LATE-01) untuk Sesi 3–5
    - Rentang data 2026-10-08..21 + Scrap Des 2025 = 0 (dari `fase_2_agent_production_2026-10-23.verifikasi_db`)
    - G024=17, G026=25, G028=0 (dari `verifikasi_db` yang sama)
    - Invariants F=4 sebagai pengecualian bisnis (dari `fase_data_cleanup_2026-10-22`)
    - `stock.group_stock_manager` sebagai data yang tidak boleh diubah dari kode (dari `known_tech_debt`)

    Lanjut ke `03-skenario.md`? Itu file terbesar (~85 skenario Sesi 0–6) — saya bisa susun bertahap per sesi bila Anda mau, atau sekaligus.