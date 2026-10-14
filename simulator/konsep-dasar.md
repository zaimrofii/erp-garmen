# Konsep Baru: **SIMULATOR GARMEN — Versi Hemat**

## Prinsip Tunggal

> **LLM hanya di tempat ambigu. Sisanya script. Django tidak tahu simulator ada.**

## Batasan Keras (jangan dilanggar)

| #   | Aturan                                              | Alasan                                                |
| --- | --------------------------------------------------- | ----------------------------------------------------- |
| 1   | LLM hanya **operator + QC**                         | Cutting/Inventory/PPIC aksinya deterministik → script |
| 2   | **1 proses Python**, async handle N agent           | Bukan 25 proses                                       |
| 3   | Django **tidak diubah** — simulator klien API biasa | Nol kontaminasi production                            |
| 4   | Event generator **rule-based**, bukan LLM           | LLM di agent, bukan di dunia                          |
| 5   | Mulai **1 line × 5 operator × 1 jam**               | Skala naik setelah stabil                             |

## Struktur (≤10 file)

```
simulator/
├── scenarios/       # YAML per klien
├── world/           # clock + event generator (rule-based)
├── agents/
│   ├── operator.py  # LLM Qwen 7B (async 5-25 virtual)
│   ├── qc.py        # LLM (defect ambiguous)
│   └── scripted.py  # rule-based: cutting, inventory, ppic
├── client/          # httpx async → Django API
├── telemetry/       # OTel exporter
└── orchestrator.py  # 1 entry point
```

## Alur

```
Clock (07:00→17:00 compressed)
    ↓ tick
Event Generator (rule-based: order, downtime, urgent)
    ↓ publish Redis
Agent Pool (1 proses async)
    ├─ LLM agent → keputusan ambiguous → HTTP call
    └─ Scripted agent → aksi deterministik → HTTP call
    ↓
Django API (existing, tidak diubah)
    ↓
Telemetry → OTel → Grafana/Sentry/Loki
```

## Realisme — 3 Hal Saja

1. **Informasi terbatas** — operator hanya tahu bundle-nya (bikin race condition muncul)
2. **Fatigue curve hardcoded** — slowdown 11:00 & 15:00 (bukan LLM)
3. **Replay** — simpan semua HTTP + LLM decision → regression test

## YAML Minimal

```yaml
scenario: "mini_1line"
factory:
  lines: 1
  operators: 5
  qc: 1
  cutting: 1
speed: 60x
duration: "07:00-17:00"
llm:
  model: "qwen2.5:7b"
  base_url: "http://ollama:11434"
anomaly:
  downtime: 0.05
  defect: 0.03
```

## Output Jujur

| Output                           | Klaim                                                                   |
| -------------------------------- | ----------------------------------------------------------------------- |
| Load test realistis              | ✅                                                                      |
| Bug discovery (race, timing)     | ✅                                                                      |
| KPI report (OEE, WIP, lead time) | ✅                                                                      |
| Regression per sprint            | ✅ (replay)                                                             |
| Ganti UAT manual                 | ⚠️ **Sebagian** — UAT teknis ya, UAT bisnis (UI/UX) tetap butuh manusia |

## Langkah Pertama (1–2 minggu)

1. Clock + event generator — 2 file
2. HTTP client + 1 scripted agent (cutting) — 2 file
3. 1 LLM agent (operator) — prompt + tool set — 3 file
4. YAML + Pydantic — 2 file
5. **Jalankan: 1 line, 5 operator, 1 jam compressed** → lihat apa yang pecah

Setelah mini: evaluasi. LLM berguna? Latency oke? Bug ketemu? **Ya → scale. Tidak → tinggalkan.**

## Kenapa Ini "Seed" Fase J, Bukan Proyek Paralel

Agent simulator & agent production (Fase J) pakai:

- Tool registry sama
- Prompt pattern sama
- Observability sama

Bangun simulator = bangun fondasi Fase J.

## Yang Harus Diputuskan Sekarang

1. LLM operator + QC saja? → **Ya**
2. Orchestrator? → **Async loop dulu**, Prefect/Celery nanti
3. Repo? → **Subfolder `simulator/`** di repo yang sama
4. Skala awal? → **1 line × 5 operator** (Qwen 7B ~10-30 tok/s, jangan langsung 75 agent)

---

## simulasi gamen besar

Konsep ini mendukung 200–500 karyawan, asalkan LLM dipakai selektif. Kuncinya: tidak semua agent pakai LLM. Dari 500 karyawan, ~90% operator jahit rutin cukup scripted (probabilitas + fatigue curve), hanya ~5% QC-kritis/rework dan ~5% supervisor/PPIC yang pakai LLM. Jadi beban LLM cuma 25–50 agent, sisanya Python async — ringan.

Yang perlu ditambah untuk skala besar: LLM pool, sharding per line, async murni, event generator di-shard, replay streaming, observability sampling.

Yang tidak berubah: Django API (sudah sanggup 500 user production), YAML config, struktur folder ≤15 file.

Rekomendasi bertahap: 5 → 25 → 50 operator per line. Jangan langsung 500. Bottleneck bukan skala, tapi rasio LLM vs scripted.
