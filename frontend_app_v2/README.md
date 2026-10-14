# MES Garmen — Frontend (v3)

Aplikasi frontend MES (Manufacturing Execution System) garmen: **React 18 + TypeScript strict + Vite + Tailwind v4 (design token OKLCH)**, data via TanStack Query, satu pintu HTTP di `integrations/api-client.ts`.

> Blueprint & kontrak: `docs/blueprint.md`, `docs/backend-contract.md` · Status: `docs/current-project.json` · Audit terakhir: `docs/fase-26-audit.md` + `docs/anti-pattern-audit.md`

## Jalankan

`bun` tidak ada di PATH Windows pada environment ini → jalankan semua perintah dari WSL:

```bash
# install
wsl -d Ubuntu -- bash -lc 'cd /home/zaimrofii/projects/odoo-garmen-project/frontend_app_v2 && /home/zaimrofii/.bun/bin/bun install'

# dev server
wsl -d Ubuntu -- bash -lc 'cd /home/zaimrofii/projects/odoo-garmen-project/frontend_app_v2 && /home/zaimrofii/.bun/bin/bun run dev'

# gate
wsl -d Ubuntu -- bash -lc 'cd /home/zaimrofii/projects/odoo-garmen-project/frontend_app_v2 && /home/zaimrofii/.bun/bin/bun run typecheck'   # 0 error
wsl -d Ubuntu -- bash -lc 'cd /home/zaimrofii/projects/odoo-garmen-project/frontend_app_v2 && /home/zaimrofii/.bun/bin/bun run lint'        # 0 error (1 warning lama)
wsl -d Ubuntu -- bash -lc 'cd /home/zaimrofii/projects/odoo-garmen-project/frontend_app_v2 && /home/zaimrofii/.bun/bin/bun x --bun vite build'
```

Build **wajib** lewat WSL (`bun --bun`) karena `node_modules` memuat binding Linux rolldown.

## Struktur

```
src/
  app/          # config, nav-config (NAV_APPS), useRole (ROLE_APPS), RoleRoute, AppRuntimeProvider, layouts/
  components/
    atoms/      # 12 atom (Button, Input, Select, Checkbox, Modal, Toast, Badge, Card, Spinner, Tabs, Textarea, Tooltip)
    molecules/  # 27 molecule (DenseTable, TableToolbar, PaginationBar, BarChart, KpiCard, RoutingGraph, AIChatBox, ...)
  pages/        # 33 halaman .tsx / 35 route di App.tsx (semua lazy kecuali Dashboard + NotFound)
  api/          # adapter per resource (pickAdapter) + real/ (api-client) + dummy/ (fixture @dummy)
  types/        # kontrak backend (snake_case)
  lib/          # tokens (design system), cn, feedback, report-period, theme/, state-display, uuid
  hooks/        # use-pagination, use-csv-export, useApiClient, use-scan, use-wide-viewport, ...
  integrations/ # api-client (satu-satunya fetch), offline-queue, use-offline-sync, ai-chat, device-binding, print-tag, ws-chatter
```

## Aturan yang dijaga gate (hasil audit Fase 26)

1. Warna hanya token OKLCH — **0** hex/rgb/palet Tailwind di seluruh `.tsx`; dark mode lewat token swap (**0** `dark:`).
2. **0** `transition-all`, **0** `key={index}`, **0** `any`/`as` paksa/`@ts-ignore`.
3. Halaman hanya impor adapter `@/api/{resource}` — **0** impor `api/real|dummy` langsung, **0** `fetch`/`apiClient` di halaman.
4. Setiap file dummy: `// @dummy` + komentar `// endpoint masa depan` + `delay()` (10/10 comply).
5. Role: sidebar & route memakai satu sumber `ROLE_APPS` — walkthrough **7 role × 35 route = 245 kombinasi**, 0 bocor.
6. Setiap aksi memberi feedback via `useFeedback().trigger(...)` → `ActionFeedback` (beep + haptic + overlay).
7. `src/styles/tailwind.css` **beku** (md5 `7E65992B0D97EFAB12A50E803F94444B`; jangan diubah).

## Statistik rilis v3

| Metrik | Nilai |
|---|---|
| Route | 35 (33 halaman + varian `:id` + `*`) |
| Atom / Molecule | 12 / 27 |
| Halaman `.tsx` | 33 |
| Chunk JS | 74 (lazy per route) |
| Bundle utama | **470,21 kB** (gzip 148,15) — ambang 500 kB |
| Gate | typecheck 0 error · lint 0 error (1 warning lama) · build hijau · warning chunk 0 · md5 CSS tetap |
