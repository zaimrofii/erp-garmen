# Simulator Garmen (MES) — MVP

Klien API murni untuk menguji Django MES: menjalankan "lantai produksi" sintetis
(clock terkompresi + event generator rule-based + agent) yang memanggil REST API
Django seperti klien biasa. **Bukan bagian production.**

## Cara jalan
```bash
python -m simulator.orchestrator -s mini_1line
# atau: python -m simulator.orchestrator --scenario mini_1line --dir simulator/scenarios
```

## Auth & env (`.env` / `.env.local`)
Simulator membaca `.env` lalu `.env.local` di folder `simulator/` (env OS tetap
menang). Variabel opsional:
- `DJANGO_SIM_COOKIE` — nilai header `Cookie` (mis. `csrftoken=...; sessionid=...`).
  WAJIB untuk endpoint `IsAuthenticated` (mis. `POST /sync/odoo/WIP/`).
- `DJANGO_SIM_TOKEN` — bearer token (header `Authorization`).
- `DJANGO_SIM_USERNAME` / `DJANGO_SIM_PASSWORD` — login admin (`/admin/login/`)
  untuk **auto-refresh cookie** saat multi-hari (kalau `sessionid` kedaluwarsa).

## Output
- `runs/{scenario}_{timestamp}.jsonl` — jejak telemetry (1 baris JSON per aksi).
- `runs/{scenario}_{timestamp}_kpi.json` — KPI agregat (success/error, latency
  p50/p95/p99, rasio llm vs scripted, breakdown per agent & endpoint).

## Prinsip
- **JANGAN ubah Django** — simulator hanya klien API.
- **JANGAN simpan state** — tanpa DB; hanya file jejak per run.
- **Replay = regression** — JSONL deterministik (RNG di-seed nama skenario).

## Struktur
```
simulator/
├── config.py          # skema YAML (Pydantic) + tool_set
├── scenarios/         # 1 YAML per skenario
├── world/             # clock (waktu terkompresi) + event generator (rule-based)
├── client/            # MESClient (httpx async → Django)
├── llm/               # OllamaClient (Qwen via Ollama)
├── agents/            # base + scripted + operator + qc
├── telemetry/         # recorder (JSONL) + kpi
├── orchestrator.py    # entry point + CLI Typer
└── README.md
```

## LLM
Agent `operator` & `qc` memakai LLM → **butuh Ollama hidup** (mis.
`http://ollama:11434`, model `qwen2.5:7b`). Kalau Ollama mati/tidak koheren,
agent **fallback ke scripted** sehingga run tetap jalan.

## Batas MVP
1 line, ≤5 operator, 1 shift. **Setelah MVP hijau: STOP** — evaluasi dulu
(LLM berguna? latency oke? bug ketemu?) sebelum scale.
