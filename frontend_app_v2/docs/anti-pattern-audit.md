frontend_app_v2/docs/anti-pattern-audit.md
markdown

# Anti-Pattern Audit — Frontend MES Garmen

> Catatan: berkas ini pada track v2 dirujuk oleh `docs/current-project.json → anti_pattern_audit.location`, tetapi belum pernah dibuat. Isi di bawah adalah **hasil audit track v3 (Fase 26)** — bagian anti-pattern murni (grep-able), bukan audit fitur.

## Metode

Semua pola diperiksa dengan grep ke `src/**` (`*.ts`, `*.tsx`; 174 file) + skrip audit runnable (parsing `App.tsx` + walkthrough 245 kombinasi role × route), dijalankan lewat WSL:

```bash
wsl -d Ubuntu -- bash -lc 'cd .../frontend_app_v2 && /home/zaimrofii/.bun/bin/bun run typecheck|run lint|x --bun vite build'
Hasil (Fase 26)
#	Anti-pattern	Pola grep	Hasil	Status
1	Warna hardcode	#[0-9a-fA-F]{3,8}\b, rgb(, rgba(, hsl(	0	✅ pass
2	OKLCH langsung di komponen	oklch( pada src/components/**, src/pages/**, src/app/**/*.tsx	0 (10 hit hanya di app/config.ts + lib/theme/apply-theme.ts = engine token)	✅ pass (accepted)
3	Palet Tailwind default	(bg|text|border|ring|from|to|via|stroke|fill)-(red|blue|…|stone)-[0-9]	0	✅ pass
4	Dark mode utility	dark:[a-z]	0	✅ pass
5	Transisi boros	transition-all (non-komentar)	0	✅ pass
6	Index sebagai key	key={index}, key={i}, key={idx} (non-komentar)	0 (4 hit = komentar larangan)	✅ pass
7	any / cast paksa	:\s*any\b, <any>, \bas\s+[A-Z], \bas\s+const, @ts-ignore, @ts-expect-error	0	✅ pass
8	Impor lapisan dalam	halaman mengimpor @/api/real/* / @/api/dummy/*	0	✅ pass
9	HTTP di halaman	await fetch(, apiClient.(get|post|request)( di pages/**	0	✅ pass
10	Legacy mati	HomePage, IndustrialButton, ScanViewfinder	0	✅ pass
11	Dummy tanpa penanda	file api/dummy/* tanpa @dummy / komentar endpoint / delay()	0 (10/10 comply)	✅ pass
12	Real tanpa header	file api/real/* tanpa // REAL	0 (5/5 comply)	✅ pass
13	Adapter berisi logic	api/*.ts tanpa pickAdapter/re-export	0 (16/16; client.ts = helper unwrap)	✅ pass
14	Route tanpa guard	route selain / dan * tanpa <RoleRoute>	0 (33 guarded / 33)	✅ pass
15	Route bocor antar-role	walkthrough 7 role × 35 route	0 mismatch (100 boleh / 145 redirect)	✅ FIXED di Fase 26
16	Menu menuju 404	item topbar tanpa route di App.tsx	0	✅ pass
17	Icon-only button tanpa nama	<button>/<Button> berisi ikon tanpa aria-label (atom content-agnostic dikecualikan)	0 dari 84 file	✅ pass
18	Aksi tanpa feedback	handler aksi tanpa useFeedback().trigger(...)	0 (34 titik trigger() di 10 file)	✅ pass
19	Bundle membengkak	warning Vite chunk > 500 kB	0 (main 470,21 kB; 74 chunk)	✅ pass
20	Token design system bocor	file yang menulis kelas tabel/kartu manual padahal token tersedia	0 (48 file memakai lib/tokens)	✅ pass
Total: 20 pemeriksaan — 19 pass, 1 fixed-during-audit (items #15), 0 fail.

Temuan yang diterima (bukan pelanggaran)
oklch() di app/config.ts + lib/theme/apply-theme.ts — engine token per-client (parseOklch → setProperty('--color-primary'|'--color-ring'|'--color-accent-blue')). Justru mekanisme yang membuat aturan "warna hanya token" bisa berlaku.

key={index} di 4 tempat = teks komentar yang melarang pola tersebut.

types/routing.ts memakai camelCase (maxWip, isRework) karena DagNode/DagEdge adalah tipe UI/editor DAG, bukan kontrak backend.

MODE.aiChat|print|wa dikonsumsi integrations/* (ai-chat.ts, print-tag.ts, ws-chatter.ts) — bukan adapter api/*, karena ketiganya bukan resource CRUD.

12 atom components/atoms/** dikecualikan dari audit aria-label: children-nya datang dari pemanggil (kewajiban a11y ada di pemanggil, dan audit menemukan 0 pelanggaran di pemanggil).

Perbaikan yang dilakukan saat audit
ID	Masalah	Perbaikan
d13-role-route-vs-role-apps	PRODUCTION_ROLES/QC_ROLES memuat admin (padahal app production bukan milik admin) dan melewatkan owner (padahal owner punya menu Production) → admin bisa buka /production/* via URL tanpa konteks TopBar; menu Production milik owner selalu redirect ke /	PRODUCTION_ROLES = ['operator','supervisor','owner'], QC_ROLES = ['qc','supervisor','operator','owner'], + konstanta BUFFER_QUEUE_ROLES/ROUTING_ROLES = ['supervisor','owner'] (hanya App.tsx)
```
